import asyncio
import json
import time
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Form, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse

from app.agent import (
    answer_from_screenshot,
    describe_calendar_screenshot,
    plan_web_task,
    route_message,
)
from app.browser_agent import run_ui_goal
from app.calendar import create_test_event, list_upcoming_events
from app.cancel import begin_run, clear_run, is_stop_message, request_cancel
from app.config import (
    PUBLIC_BASE_URL,
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN,
    TWILIO_WHATSAPP_NUMBER,
)
from app.gmail import list_recent_inbox
from app.live import subscribe, unsubscribe
from app.insights import summarize_runs
from app.runs import log_run, read_runs
from app.screenshot import (
    CALENDAR_WEEK_URL,
    capture_calendar_screenshot,
    capture_event_screenshot,
)
from app.session import (
    MAX_ASKS,
    Pending,
    clear_pending,
    extract_url,
    get_pending,
    missing_schedule_slots,
    schedule_followup,
    set_pending,
)

ROOT = Path(__file__).resolve().parent.parent
SCREENSHOT_DIR = ROOT / "screenshots"
STATIC_DIR = Path(__file__).resolve().parent / "static"
SCREENSHOT_DIR.mkdir(exist_ok=True)

app = FastAPI(title="Mira")
app.mount("/screenshots", StaticFiles(directory=str(SCREENSHOT_DIR)), name="screenshots")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/dashboard")
def dashboard():
    return FileResponse(STATIC_DIR / "dashboard.html")


@app.get("/dashboard/runs")
def dashboard_runs():
    return read_runs()


@app.get("/dashboard/summary")
def dashboard_summary():
    return summarize_runs()


@app.get("/dashboard/stream")
async def dashboard_stream():
    sub = subscribe()

    async def events():
        try:
            while True:
                event = await asyncio.to_thread(sub.get)
                yield f"data: {json.dumps(event)}\n\n"
        finally:
            unsubscribe(sub)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


def event_line(event):
    start = event["start"].get("dateTime", event["start"].get("date"))
    return f"{start} {event.get('summary', '(no title)')}"


def parse_mode(body: str) -> tuple[str, str]:
    stripped = body.strip()
    if stripped.lower().startswith("screen:"):
        return "screen", stripped[7:].strip()
    return "api", stripped


def send_whatsapp(to: str, body: str, media_url: str | None = None):
    kwargs = {
        "from_": TWILIO_WHATSAPP_NUMBER,
        "to": to,
        "body": body,
    }
    if media_url:
        kwargs["media_url"] = [media_url]
    message = twilio_client.messages.create(**kwargs)
    print(f"Sent WhatsApp sid={message.sid} status={message.status}")


async def screen_list_and_reply(to: str):
    started = time.perf_counter()
    try:
        path = await asyncio.to_thread(capture_calendar_screenshot)
        text = await asyncio.to_thread(describe_calendar_screenshot, path)
        seconds = round(time.perf_counter() - started, 2)
        media_url = f"{PUBLIC_BASE_URL}/screenshots/{path.name}"
        print(f"Screenshot: {media_url}")
        print(text)
        log_run(
            mode="screen",
            task="list",
            task_class="list",
            outcome="ok",
            seconds=seconds,
            steps=1,
            detail="screenshot+vision",
        )
        await asyncio.to_thread(send_whatsapp, to, text, media_url)
    except Exception as error:
        log_run(
            mode="screen",
            task="list",
            task_class="list",
            outcome="fail",
            seconds=round(time.perf_counter() - started, 2),
            error=str(error),
        )
        print(error)
        await asyncio.to_thread(send_whatsapp, to, "Screen calendar request failed.")


async def screen_schedule_and_reply(to: str, title: str, when: str):
    when_bit = f" starting at {when}" if when else ""
    goal = f"create an event titled {title}{when_bit}"
    cancel = begin_run(to)
    try:
        result = await asyncio.to_thread(run_ui_goal, CALENDAR_WEEK_URL, goal, cancel)
        path = result["screenshot"]
        media_url = f"{PUBLIC_BASE_URL}/screenshots/{path.name}"
        print(f"Screenshot: {media_url}")
        print(result["message"])
        log_run(
            mode="screen",
            task="schedule",
            task_class="schedule",
            title=title,
            when=when,
            outcome=result["outcome"],
            seconds=result["seconds"],
            steps=result["steps"],
            actions=result["actions"],
            detail=result["message"],
        )
        await asyncio.to_thread(send_whatsapp, to, result["message"], media_url)
    except Exception as error:
        log_run(
            mode="screen",
            task="schedule",
            task_class="schedule",
            title=title,
            when=when,
            outcome="fail",
            error=str(error),
        )
        print(error)
        await asyncio.to_thread(send_whatsapp, to, "Screen schedule request failed.")
    finally:
        clear_run(to)


async def screen_web_and_reply(to: str, url: str, goal: str, task_class: str = "web"):
    site = url.split("/")[2] if "://" in url else url
    cancel = begin_run(to)
    try:
        result = await asyncio.to_thread(run_ui_goal, url, goal, cancel)
        path = result["screenshot"]
        media_url = f"{PUBLIC_BASE_URL}/screenshots/{path.name}"
        if result["outcome"] in {"done", "timeout"}:
            reply_text = await asyncio.to_thread(answer_from_screenshot, path, goal)
        elif result["outcome"] == "cancelled":
            reply_text = "Stopped."
        else:
            reply_text = result["message"]
        print(f"Screenshot: {media_url}")
        print(reply_text)
        log_run(
            mode="screen",
            task="web",
            task_class=task_class,
            outcome=result["outcome"],
            seconds=result["seconds"],
            steps=result["steps"],
            actions=result["actions"],
            detail=reply_text,
            site=site,
            goal=goal,
            url=url,
        )
        await asyncio.to_thread(send_whatsapp, to, reply_text, media_url)
    except Exception as error:
        log_run(
            mode="screen",
            task="web",
            task_class=task_class,
            outcome="fail",
            error=str(error),
            site=site,
            goal=goal,
            url=url,
        )
        print(error)
        await asyncio.to_thread(send_whatsapp, to, "Screen web task failed.")
    finally:
        clear_run(to)


def merge_schedule_fields(pending: Pending, route: dict) -> Pending:
    return Pending(
        action="schedule",
        mode=pending.mode,
        title=route.get("title") or pending.title,
        when=route.get("when") or pending.when,
        asks=pending.asks,
        notes=pending.notes,
    )


def start_or_continue_schedule(user: str, mode: str, route: dict) -> tuple[str | None, Pending | None]:
    pending = get_pending(user)
    if pending and pending.action == "schedule":
        pending = merge_schedule_fields(pending, route)
    else:
        pending = Pending(
            action="schedule",
            mode=mode,
            title=route.get("title") or "",
            when=route.get("when") or "",
        )

    missing = missing_schedule_slots(pending.title, pending.when)
    if not missing:
        clear_pending(user)
        return None, pending

    pending.asks += 1
    if pending.asks > MAX_ASKS:
        clear_pending(user)
        return (
            "Still missing details after two follow-ups. "
            "Try again with a title and day/time, e.g. schedule Costco Friday 9pm."
        ), None

    set_pending(user, pending)
    return schedule_followup(missing), None


def handle_web_plan(user: str, plan: dict) -> tuple[str | None, Pending | None]:
    """Return (ask_text, ready_pending)."""
    goal = plan.get("goal") or ""
    url = plan.get("start_url") or ""
    ask = plan.get("ask_user") or ""
    task_class = plan.get("task_class") or "other"

    if url and not ask:
        return None, Pending(
            action="web",
            mode="screen",
            goal=goal,
            url=url,
            task_class=task_class,
        )

    if ask or not url:
        pending = Pending(
            action="web",
            mode="screen",
            goal=goal,
            url=url,
            task_class=task_class,
            asks=1,
        )
        set_pending(user, pending)
        return ask or "What URL should I open for this?", None

    return None, Pending(
        action="web",
        mode="screen",
        goal=goal,
        url=url,
        task_class=task_class,
    )


def continue_web_pending(user: str, message: str) -> tuple[str | None, Pending | None]:
    pending = get_pending(user)
    if not pending or pending.action != "web":
        return None, None

    url = extract_url(message) or pending.url
    if url:
        pending.url = url
        clear_pending(user)
        return None, pending

    pending.asks += 1
    if pending.asks > MAX_ASKS:
        clear_pending(user)
        return (
            "Still need a URL after two follow-ups. "
            "Send the link (https://...) and I'll continue."
        ), None

    set_pending(user, pending)
    return "Please send the https link for that site.", None


@app.post("/webhook/whatsapp")
async def whatsapp_webhook(
    background_tasks: BackgroundTasks,
    From: str = Form(...),
    Body: str = Form(""),
):
    print(f"Incoming WhatsApp from {From}: {Body}")
    text = "Tell me what you need — calendar, mail, or a web task (I can browse on screen)."
    media_url = None
    mode = "api"

    try:
        mode, message = parse_mode(Body)
        print(f"Mode: {mode}")

        if is_stop_message(message):
            clear_pending(From)
            if request_cancel(From):
                text = "Stopping the current screen task..."
            else:
                text = "Nothing running to stop."
            print(text)
            reply = MessagingResponse()
            reply.message(text)
            return Response(content=str(reply), headers={"Content-Type": "text/xml"})

        pending = get_pending(From)

        # Continue web clarification (usually waiting on a private URL).
        if pending and pending.action == "web":
            ask, ready = continue_web_pending(From, message)
            if ask:
                text = ask
            elif ready:
                background_tasks.add_task(
                    screen_web_and_reply,
                    From,
                    ready.url,
                    ready.goal,
                    ready.task_class,
                )
                text = "On it..."
            print(text)
            reply = MessagingResponse()
            reply.message(text)
            return Response(content=str(reply), headers={"Content-Type": "text/xml"})

        route_body = message
        if pending and pending.action == "schedule":
            mode = pending.mode
            if pending.title and not pending.when:
                route_body = f"schedule {pending.title} {message}"
            elif pending.when and not pending.title:
                route_body = f"schedule {message} {pending.when}"
            else:
                route_body = f"schedule {message}"

        route = await asyncio.to_thread(route_message, route_body)
        print(f"Route: {route}")

        if pending and pending.action == "schedule":
            followup, ready = start_or_continue_schedule(From, pending.mode, {
                "title": route.get("title") or pending.title,
                "when": route.get("when") or pending.when,
            })
            if followup:
                text = followup
            elif ready:
                if ready.mode == "screen":
                    background_tasks.add_task(
                        screen_schedule_and_reply, From, ready.title, ready.when
                    )
                    text = "Creating that on screen..."
                else:
                    started = time.perf_counter()
                    event = await asyncio.to_thread(create_test_event, ready.title, ready.when)
                    text = f"Created {event_line(event)}"
                    event_url = event.get("htmlLink")
                    if event_url:
                        path = await asyncio.to_thread(capture_event_screenshot, event_url)
                        media_url = f"{PUBLIC_BASE_URL}/screenshots/{path.name}"
                    log_run(
                        mode="api",
                        task="schedule",
                        task_class="schedule",
                        title=ready.title,
                        when=ready.when,
                        outcome="ok",
                        seconds=round(time.perf_counter() - started, 2),
                        steps=0,
                        detail=text,
                    )
            print(text)
            reply = MessagingResponse()
            message_out = reply.message(text)
            if media_url:
                message_out.media(media_url)
            return Response(content=str(reply), headers={"Content-Type": "text/xml"})

        action = route["action"]

        if action == "list" and mode == "screen":
            clear_pending(From)
            background_tasks.add_task(screen_list_and_reply, From)
            text = "Checking your calendar..."
        elif action == "list":
            clear_pending(From)
            started = time.perf_counter()
            events = await asyncio.to_thread(list_upcoming_events)
            text = "\n".join(event_line(event) for event in events) or "No upcoming events found."
            log_run(
                mode="api",
                task="list",
                task_class="list",
                outcome="ok",
                seconds=round(time.perf_counter() - started, 2),
                steps=0,
                detail=f"{len(events)} events",
            )
        elif action == "schedule":
            followup, ready = start_or_continue_schedule(From, mode, route)
            if followup:
                text = followup
            elif ready:
                clear_pending(From)
                if mode == "screen":
                    background_tasks.add_task(
                        screen_schedule_and_reply, From, ready.title, ready.when
                    )
                    text = "Creating that on screen..."
                else:
                    started = time.perf_counter()
                    event = await asyncio.to_thread(create_test_event, ready.title, ready.when)
                    text = f"Created {event_line(event)}"
                    event_url = event.get("htmlLink")
                    if event_url:
                        path = await asyncio.to_thread(capture_event_screenshot, event_url)
                        media_url = f"{PUBLIC_BASE_URL}/screenshots/{path.name}"
                        print(f"Screenshot: {media_url}")
                    log_run(
                        mode="api",
                        task="schedule",
                        task_class="schedule",
                        title=ready.title,
                        when=ready.when,
                        outcome="ok",
                        seconds=round(time.perf_counter() - started, 2),
                        steps=0,
                        detail=text,
                    )
        elif action == "mail":
            clear_pending(From)
            started = time.perf_counter()
            subjects = await asyncio.to_thread(list_recent_inbox)
            text = "\n".join(subjects) or "No inbox messages found."
            log_run(
                mode="api",
                task="mail",
                task_class="mail",
                outcome="ok",
                seconds=round(time.perf_counter() - started, 2),
                steps=0,
                detail=f"{len(subjects)} messages",
            )
        elif action in {"web", "help"}:
            # Web/browse tasks always use the screenshot agent (API cannot browse).
            # No site-specific hardcoding — planner infers a public start URL when possible.
            clear_pending(From)
            plan = await asyncio.to_thread(plan_web_task, message)
            print(f"Web plan: {plan}")
            ask, ready = handle_web_plan(From, plan)
            if ask:
                text = ask
            elif ready and ready.url:
                background_tasks.add_task(
                    screen_web_and_reply,
                    From,
                    ready.url,
                    ready.goal,
                    ready.task_class,
                )
                text = "On it..."
            else:
                text = "Tell me what you need — calendar, mail, or a web task."
        else:
            clear_pending(From)
    except Exception as error:
        text = "Request failed."
        print(error)
        log_run(mode=mode, task="unknown", outcome="fail", error=str(error))

    print(text)
    reply = MessagingResponse()
    message_out = reply.message(text)
    if media_url:
        message_out.media(media_url)
    return Response(content=str(reply), headers={"Content-Type": "text/xml"})

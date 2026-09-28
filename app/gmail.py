from googleapiclient.discovery import build

from app.calendar import get_credentials


def list_recent_inbox(max_results=5):
    service = build("gmail", "v1", credentials=get_credentials())
    result = (
        service.users()
        .messages()
        .list(userId="me", maxResults=max_results, labelIds=["INBOX"])
        .execute()
    )
    subjects = []
    for item in result.get("messages", []):
        message = (
            service.users()
            .messages()
            .get(
                userId="me",
                id=item["id"],
                format="metadata",
                metadataHeaders=["Subject"],
            )
            .execute()
        )
        headers = message.get("payload", {}).get("headers", [])
        subject = next((header["value"] for header in headers if header["name"] == "Subject"), None)
        subjects.append(subject or "(no subject)")
    return subjects

import firebase_admin
from firebase_admin import credentials, messaging
import os

# Initialize Firebase Admin SDK (once)
if not firebase_admin._apps:
    cred = credentials.Certificate(os.environ["FIREBASE_SERVICE_ACCOUNT_PATH"])
    firebase_admin.initialize_app(cred)


async def send_fcm_notification(
    token: str, title: str, body: str, data: dict = None
):
    try:
        message = messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            data={k: str(v) for k, v in (data or {}).items()},
            android=messaging.AndroidConfig(priority="high"),
            token=token,
        )
        response = messaging.send(message)
        return {"success": True, "message_id": response}
    except Exception as e:
        return {"success": False, "error": str(e)}

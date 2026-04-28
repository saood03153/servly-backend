import firebase_admin
from firebase_admin import credentials, messaging
import os
import json
import tempfile

# Initialize Firebase Admin SDK (once)
if not firebase_admin._apps:
    # Support both file path and inline JSON (for Railway/Cloud Run deployment)
    sa_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
    sa_path = os.environ.get("FIREBASE_SERVICE_ACCOUNT_PATH")

    if sa_json:
        # Write JSON string to a temp file
        sa_dict = json.loads(sa_json)
        tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
        json.dump(sa_dict, tmp)
        tmp.close()
        cred = credentials.Certificate(tmp.name)
    elif sa_path:
        cred = credentials.Certificate(sa_path)
    else:
        raise RuntimeError("No Firebase credentials found. Set FIREBASE_SERVICE_ACCOUNT_JSON or FIREBASE_SERVICE_ACCOUNT_PATH")

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

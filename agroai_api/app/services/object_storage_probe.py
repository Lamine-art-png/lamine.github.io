from app.services.object_storage import get_object_store, object_storage_configured


def probe_object_storage() -> dict:
    if not object_storage_configured():
        return {"configured": False, "reachable": False}
    store = get_object_store()
    store.client.head_bucket(Bucket=store.bucket)
    return {"configured": True, "reachable": True}

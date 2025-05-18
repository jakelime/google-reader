import datetime
import hashlib
import json


def get_utc_timestamp_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def create_dict_hash(data_dict: dict):
    """
    Creates a unique SHA-256 hash for a dictionary.

    Args:
      data_dict: The dictionary to hash.

    Returns:
      A hexadecimal string representing the SHA-256 hash.
    """
    if not isinstance(data_dict, dict):
        raise TypeError("Input must be a dictionary")

    serialized_data = json.dumps(data_dict, sort_keys=True, separators=(",", ":"))
    encoded_data = serialized_data.encode("utf-8")
    hasher = hashlib.sha256()
    hasher.update(encoded_data)
    unique_hash = hasher.hexdigest()
    return unique_hash

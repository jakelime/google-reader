import datetime
import hashlib
import json
import copy


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


def hash_metadata(metadata, timestamp_key: str = "rcv_date"):
    """
    Hashes the provided metadata dictionary.

    Args:
      metadata: A dictionary containing metadata, including a datetime object.

    Returns:
      A hexadecimal string representation of the hash.
    """
    meta = copy.deepcopy(metadata)
    # Convert the datetime object to a consistent string representation
    # ISO 8601 format is a good standard for this.
    if isinstance(metadata.get(timestamp_key), datetime.datetime):
        meta[timestamp_key] = metadata[timestamp_key].isoformat()

    # Convert the dictionary to a JSON string.
    # Using sort_keys=True ensures that the order of keys doesn't affect the hash.
    meta_str = json.dumps(meta, sort_keys=True)
    hasher = hashlib.sha256()
    hasher.update(meta_str.encode("utf-8"))
    return hasher.hexdigest()

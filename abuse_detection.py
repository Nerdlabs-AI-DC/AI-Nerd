import time
import hashlib
import threading
from collections import defaultdict
from datetime import datetime, timezone, timedelta
import storage

_LOCK = threading.Lock()

# Configuration
EMPTY_MESSAGE_POINTS = 1
DUPLICATE_MESSAGE_POINTS = 2
HIGH_FREQUENCY_POINTS = 5  # For >20 messages/hour
RAPID_FIRE_POINTS = 10  # For multiple messages <1 second
ABUSE_SCORE_DECAY_DAYS = 7  # Points decay over this period

# In-memory cache for current session
_message_cache = defaultdict(list)
_abuse_scores = {}


def _get_content_hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def _is_empty_message(content: str) -> bool:
    return not content or not content.strip()


def _calculate_similarity(hash1: str, hash2: str) -> float:
    if hash1 == hash2:
        return 1.0
    return 0.0


def track_message(user_id: int, content: str) -> None:
    if not content:
        return
    
    now = time.time()
    content_hash = _get_content_hash(content)
    content_len = len(content)
    
    with _LOCK:
        user_messages = _message_cache[user_id]
        user_messages.append((now, content_hash, content_len))
        
        if len(user_messages) > 100:
            user_messages.pop(0)
        
        try:
            storage.add_abuse_tracking_record(user_id, content_hash, content_len, now)
        except Exception:
            pass


def calculate_abuse_score(user_id: int) -> dict:
    try:
        records = storage.get_abuse_tracking_records(user_id)
    except Exception:
        records = []
    
    if not records:
        return {
            'user_id': user_id,
            'score': 0,
            'empty_messages': 0,
            'duplicate_messages': 0,
            'messages_per_hour': 0,
            'rapid_fire_count': 0,
            'last_24h_messages': 0
        }
    
    now = time.time()
    day_ago = now - (24 * 3600)
    last_hour_ago = now - 3600
    week_ago = now - (7 * 24 * 3600)
    
    score = 0
    empty_count = 0
    duplicate_count = 0
    rapid_fire_count = 0
    messages_24h = 0
    messages_1h = 0
    
    recent_records = [r for r in records if r['timestamp'] > week_ago]
    
    recent_records.reverse()
    
    seen_hashes = {}
    
    for i, record in enumerate(recent_records):
        timestamp = record['timestamp']
        content_hash = record['content_hash']
        content_len = record['content_len']
        
        if timestamp > day_ago:
            messages_24h += 1
        
        if timestamp > last_hour_ago:
            messages_1h += 1

        if content_len == 0 or (content_hash == _get_content_hash('')):
            empty_count += 1
            age_days = (now - timestamp) / (24 * 3600)
            decay_factor = max(0.1, 1.0 - (age_days / ABUSE_SCORE_DECAY_DAYS))
            score += int(EMPTY_MESSAGE_POINTS * decay_factor)

        if content_hash in seen_hashes:
            duplicate_count += 1
            prev_timestamp = seen_hashes[content_hash]
            age_days = (now - timestamp) / (24 * 3600)
            decay_factor = max(0.1, 1.0 - (age_days / ABUSE_SCORE_DECAY_DAYS))
            score += int(DUPLICATE_MESSAGE_POINTS * decay_factor)
        
        seen_hashes[content_hash] = timestamp
        
        if i > 0:
            prev_timestamp = recent_records[i - 1]['timestamp']
            if abs(timestamp - prev_timestamp) < 1.0:
                rapid_fire_count += 1
                age_days = (now - timestamp) / (24 * 3600)
                decay_factor = max(0.1, 1.0 - (age_days / ABUSE_SCORE_DECAY_DAYS))
                score += int(RAPID_FIRE_POINTS * decay_factor)
    
    if messages_1h > 20:
        score += HIGH_FREQUENCY_POINTS
    
    return {
        'user_id': user_id,
        'score': int(score),
        'empty_messages': empty_count,
        'duplicate_messages': duplicate_count,
        'messages_per_hour': messages_1h,
        'rapid_fire_count': rapid_fire_count,
        'last_24h_messages': messages_24h
    }


def get_top_suspicious_users(limit: int = 20) -> list:
    try:
        all_users = storage.get_all_tracked_users()
    except Exception:
        return []
    
    users_with_scores = []
    for user_id in all_users:
        score_data = calculate_abuse_score(user_id)
        if score_data['score'] > 0:
            users_with_scores.append(score_data)
    
    users_with_scores.sort(key=lambda x: x['score'], reverse=True)
    
    return users_with_scores[:limit]


def get_user_message_history(user_id: int, limit: int = 50) -> list:
    try:
        records = storage.get_abuse_tracking_records(user_id, limit=limit)
    except Exception:
        return []
    
    return records


def clear_user_tracking(user_id: int) -> bool:
    try:
        storage.clear_abuse_tracking_records(user_id)
        with _LOCK:
            if user_id in _message_cache:
                del _message_cache[user_id]
        return True
    except Exception:
        return False


def get_stats() -> dict:
    try:
        total_tracked = storage.get_tracked_users_count()
        high_risk = len([u for u in get_top_suspicious_users(limit=1000) if u['score'] > 50])
    except Exception:
        total_tracked = 0
        high_risk = 0
    
    return {
        'total_tracked_users': total_tracked,
        'high_risk_users': high_risk
    }

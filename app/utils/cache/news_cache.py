# app/utils/cache/news_cache.py

from redis import Redis
import json
from typing import Optional, Any
import pickle
from datetime import timedelta
import os

class NewsCache:
    def __init__(self):
        """Initialize Redis cache connection"""
        self.redis = Redis(
            host=os.getenv('REDIS_HOST', 'localhost'),
            port=int(os.getenv('REDIS_PORT', 6379)),
            db=int(os.getenv('REDIS_DB', 0)),
            password=os.getenv('REDIS_PASSWORD', None),
            decode_responses=True  # For string data
        )
        self.binary_redis = Redis(  # For binary data (pickle)
            host=os.getenv('REDIS_HOST', 'localhost'),
            port=int(os.getenv('REDIS_PORT', 6379)),
            db=int(os.getenv('REDIS_DB', 0)),
            password=os.getenv('REDIS_PASSWORD', None)
        )

    def get_json(self, key: str) -> Optional[Any]:
        """Get JSON data from cache"""
        data = self.redis.get(key)
        if data:
            return json.loads(data)
        return None

    def set_json(self, key: str, value: Any, expire: int = 3600):
        """Set JSON data in cache with expiration"""
        self.redis.set(key, json.dumps(value), ex=expire)

    def get_object(self, key: str) -> Optional[Any]:
        """Get pickled object from cache"""
        data = self.binary_redis.get(key)
        if data:
            return pickle.loads(data)
        return None

    def set_object(self, key: str, value: Any, expire: int = 3600):
        """Set pickled object in cache with expiration"""
        self.binary_redis.set(key, pickle.dumps(value), ex=expire)

    def build_key(self, *args) -> str:
        """Build cache key from arguments"""
        return ':'.join(str(arg) for arg in args)

    def delete_pattern(self, pattern: str):
        """Delete all keys matching pattern"""
        for key in self.redis.scan_iter(pattern):
            self.redis.delete(key)
            
    def get_or_set(self, key: str, callback, expire: int = 3600):
        """Get from cache or set if not exists"""
        data = self.get_json(key)
        if data is None:
            data = callback()
            if data is not None:
                self.set_json(key, data, expire)
        return data
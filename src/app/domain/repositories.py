"""Canonical repository surface."""

from ..crud.crud_posts import CRUDPost, crud_posts
from ..crud.crud_rate_limit import CRUDRateLimit, crud_rate_limits
from ..crud.crud_tier import CRUDTier, crud_tiers
from ..crud.crud_users import CRUDUser, crud_users

post_repository = crud_posts
rate_limit_repository = crud_rate_limits
tier_repository = crud_tiers
user_repository = crud_users

__all__ = [
    "CRUDPost",
    "CRUDRateLimit",
    "CRUDTier",
    "CRUDUser",
    "crud_posts",
    "crud_rate_limits",
    "crud_tiers",
    "crud_users",
    "post_repository",
    "rate_limit_repository",
    "tier_repository",
    "user_repository",
]

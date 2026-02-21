"""
OASIS Forum - Data models
"""

from pydantic import BaseModel, Field
from enum import Enum
from typing import Optional


class DiscussionStatus(str, Enum):
    PENDING = "pending"
    DISCUSSING = "discussing"
    CONCLUDED = "concluded"
    ERROR = "error"


class CreateTopicRequest(BaseModel):
    """Request body for creating a new discussion topic."""
    question: str
    user_id: str = "anonymous"
    max_rounds: int = Field(default=5, ge=1, le=20)
    expert_tags: list[str] = []  # Empty = all experts participate
    schedule_yaml: Optional[str] = None  # Inline YAML schedule string
    schedule_file: Optional[str] = None  # Path to YAML schedule file
    use_bot_session: bool = False  # True = experts use bot sessions (stateful, with tools)
    bot_enabled_tools: Optional[list[str]] = None  # Tool whitelist for bot session experts


class PostInfo(BaseModel):
    """Single post in a discussion thread."""
    id: int
    author: str
    content: str
    reply_to: Optional[int] = None
    upvotes: int = 0
    downvotes: int = 0
    timestamp: float


class TopicDetail(BaseModel):
    """Full detail of a discussion topic."""
    topic_id: str
    question: str
    status: DiscussionStatus
    current_round: int
    max_rounds: int
    posts: list[PostInfo]
    conclusion: Optional[str] = None


class TopicSummary(BaseModel):
    """Brief summary of a discussion topic (for listing)."""
    topic_id: str
    question: str
    status: DiscussionStatus
    post_count: int
    current_round: int
    max_rounds: int
    created_at: float

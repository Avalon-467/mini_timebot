"""
OASIS Forum - Thread-safe discussion board
"""

import asyncio
import time
from dataclasses import dataclass, field


@dataclass
class Post:
    """A single post / reply in a discussion thread."""
    id: int
    author: str
    content: str
    reply_to: int | None = None
    upvotes: int = 0
    downvotes: int = 0
    timestamp: float = field(default_factory=time.time)
    voters: dict[str, str] = field(default_factory=dict)  # voter_name -> "up"/"down"


class DiscussionForum:
    """
    Thread-safe shared discussion board for a single topic.
    All experts read/write through this instance concurrently.
    """

    def __init__(self, topic_id: str, question: str, user_id: str = "anonymous", max_rounds: int = 5):
        self.topic_id = topic_id
        self.question = question
        self.user_id = user_id
        self.max_rounds = max_rounds
        self.current_round = 0
        self.posts: list[Post] = []
        self.conclusion: str | None = None
        self.status = "pending"
        self.created_at = time.time()
        self._lock = asyncio.Lock()
        self._counter = 0

    async def publish(self, author: str, content: str, reply_to: int | None = None) -> Post:
        """Publish a new post to the forum (thread-safe)."""
        async with self._lock:
            self._counter += 1
            post = Post(
                id=self._counter,
                author=author,
                content=content,
                reply_to=reply_to,
            )
            self.posts.append(post)
            return post

    async def vote(self, voter: str, post_id: int, direction: str):
        """Vote on a post. Each voter can only vote once per post, cannot vote on own posts."""
        async with self._lock:
            post = self._find(post_id)
            if post and voter != post.author and voter not in post.voters:
                post.voters[voter] = direction
                if direction == "up":
                    post.upvotes += 1
                else:
                    post.downvotes += 1

    async def browse(self, viewer: str | None = None, exclude_self: bool = False) -> list[Post]:
        """Browse all posts. Optionally exclude the viewer's own posts."""
        async with self._lock:
            if exclude_self and viewer:
                return [p for p in self.posts if p.author != viewer]
            return list(self.posts)

    async def get_top_posts(self, n: int = 3) -> list[Post]:
        """Get the top N posts ranked by net upvotes."""
        async with self._lock:
            return sorted(
                self.posts,
                key=lambda p: p.upvotes - p.downvotes,
                reverse=True,
            )[:n]

    async def get_post_count(self) -> int:
        """Get total number of posts."""
        async with self._lock:
            return len(self.posts)

    def _find(self, post_id: int) -> Post | None:
        """Find a post by ID (caller must hold lock)."""
        return next((p for p in self.posts if p.id == post_id), None)

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from story_app.core.database import Base


class EventRole(str, enum.Enum):
    REQUIRES = "REQUIRES"
    CREATES = "CREATES"
    REFERENCES = "REFERENCES"


class Story(Base):
    __tablename__ = "stories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    characters: Mapped[list["StoryCharacter"]] = relationship(
        "StoryCharacter", back_populates="story", cascade="all, delete-orphan"
    )
    events: Mapped[list["StoryEvent"]] = relationship(
        "StoryEvent", back_populates="story", cascade="all, delete-orphan"
    )


class StoryCharacter(Base):
    __tablename__ = "story_characters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    story_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("stories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    character_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    story: Mapped["Story"] = relationship("Story", back_populates="characters")

    __table_args__ = (UniqueConstraint("story_id", "character_id", name="uq_story_character"),)


class StoryEvent(Base):
    __tablename__ = "story_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    story_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("stories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    role: Mapped[EventRole] = mapped_column(
        Enum(EventRole), default=EventRole.REFERENCES, nullable=False
    )

    story: Mapped["Story"] = relationship("Story", back_populates="events")

    __table_args__ = (UniqueConstraint("story_id", "event_id", "role", name="uq_story_event_role"),)

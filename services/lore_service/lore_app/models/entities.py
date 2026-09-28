import enum
from datetime import datetime

from lore_app.core.database import Base
from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship


class CharacterType(str, enum.Enum):
    COMPANION = "COMPANION"
    NPC = "NPC"
    PROTAGONIST = "PROTAGONIST"
    ANTAGONIST = "ANTAGONIST"


class EventType(str, enum.Enum):
    COMPANION_JOIN = "COMPANION_JOIN"
    NPC_APPEAR = "NPC_APPEAR"
    REVELATION = "REVELATION"
    RELATIONSHIP = "RELATIONSHIP"
    WORLD_STATE = "WORLD_STATE"
    PLOT_MILESTONE = "PLOT_MILESTONE"


class ParticipantRole(str, enum.Enum):
    INITIATOR = "INITIATOR"
    TARGET = "TARGET"
    PARTICIPANT = "PARTICIPANT"
    WITNESS = "WITNESS"


class Character(Base):
    __tablename__ = "characters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    type: Mapped[CharacterType] = mapped_column(
        Enum(CharacterType), default=CharacterType.COMPANION, nullable=False
    )
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    participations: Mapped[list["EventParticipant"]] = relationship(
        "EventParticipant", back_populates="character", cascade="all, delete-orphan"
    )


class WorldEvent(Base):
    __tablename__ = "world_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200), unique=True, nullable=False, index=True)
    type: Mapped[EventType] = mapped_column(
        Enum(EventType), default=EventType.PLOT_MILESTONE, nullable=False
    )
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    participants: Mapped[list["EventParticipant"]] = relationship(
        "EventParticipant", back_populates="event", cascade="all, delete-orphan"
    )
    # Direct dependencies where this event is child (depends on parent)
    parent_edges: Mapped[list["EventDependency"]] = relationship(
        "EventDependency",
        foreign_keys="EventDependency.child_id",
        back_populates="child_event",
        cascade="all, delete-orphan",
    )
    # Direct dependencies where this event is parent (child depends on this)
    child_edges: Mapped[list["EventDependency"]] = relationship(
        "EventDependency",
        foreign_keys="EventDependency.parent_id",
        back_populates="parent_event",
        cascade="all, delete-orphan",
    )


class EventDependency(Base):
    """Represents directed edge parent -> child (child requires parent)."""

    __tablename__ = "event_dependencies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    parent_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("world_events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    child_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("world_events.id", ondelete="CASCADE"), nullable=False, index=True
    )

    parent_event: Mapped["WorldEvent"] = relationship(
        "WorldEvent", foreign_keys=[parent_id], back_populates="child_edges"
    )
    child_event: Mapped["WorldEvent"] = relationship(
        "WorldEvent", foreign_keys=[child_id], back_populates="parent_edges"
    )

    __table_args__ = (
        UniqueConstraint("parent_id", "child_id", name="uq_event_dependency_parent_child"),
    )


class EventParticipant(Base):
    __tablename__ = "event_participants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("world_events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    character_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("characters.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[ParticipantRole] = mapped_column(
        Enum(ParticipantRole), default=ParticipantRole.PARTICIPANT, nullable=False
    )

    event: Mapped["WorldEvent"] = relationship("WorldEvent", back_populates="participants")
    character: Mapped["Character"] = relationship("Character", back_populates="participations")

    __table_args__ = (
        UniqueConstraint("event_id", "character_id", name="uq_event_participant_event_character"),
    )

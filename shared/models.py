from datetime import datetime

from sqlalchemy import BigInteger, String, DateTime, ForeignKey, Boolean, JSON, func, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.database import Base


class User(Base):
    __tablename__ = "users"

    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    first_name: Mapped[str] = mapped_column(String(255), nullable=False)
    language_code: Mapped[str] = mapped_column(String(10), default="uz", nullable=False)
    subscription_type: Mapped[str] = mapped_column(
        String(50), default="free", server_default="free", nullable=False
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), server_default=func.now()
    )

    # Relationships
    subscriptions = relationship(
        "Subscription", back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User telegram_id={self.telegram_id} language_code={self.language_code}>"


class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        Index("idx_subscriptions_active_date", "is_active", "date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), nullable=False
    )
    origin_name: Mapped[str] = mapped_column(String(255), nullable=False)
    destination_name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Station/city codes for API lookups (nullable depending on transport type selected)
    train_dep_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    train_arv_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    bus_dep_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    bus_arv_id: Mapped[str | None] = mapped_column(String(50), nullable=True)

    date: Mapped[str] = mapped_column(String(10), nullable=False)  # Format: YYYY-MM-DD
    transport_type: Mapped[str] = mapped_column(String(20), nullable=False)  # train, bus, both
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), server_default=func.now()
    )

    # Relationships
    user = relationship("User", back_populates="subscriptions")
    state = relationship(
        "SubscriptionState",
        back_populates="subscription",
        cascade="all, delete-orphan",
        uselist=False,
    )

    def __repr__(self) -> str:
        return f"<Subscription id={self.id} user_id={self.user_id} route={self.origin_name}->{self.destination_name} date={self.date}>"


class SubscriptionState(Base):
    __tablename__ = "subscription_states"

    subscription_id: Mapped[int] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="CASCADE"), primary_key=True
    )
    last_state: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), server_default=func.now()
    )

    # Relationships
    subscription = relationship("Subscription", back_populates="state")

    def __repr__(self) -> str:
        return f"<SubscriptionState subscription_id={self.subscription_id}>"

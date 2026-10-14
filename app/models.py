import enum
from datetime import date, datetime, time

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class BookingStatus(str, enum.Enum):
    pending = "pending"          # створено, очікує на бажаний час (резерв)
    confirmed = "confirmed"      # підтверджено (за замовчуванням одразу після створення)
    cancelled_client = "cancelled_client"
    cancelled_master = "cancelled_master"
    completed = "completed"
    no_show = "no_show"


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(primary_key=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    marketing_opt_in: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    bookings: Mapped[list["Booking"]] = relationship(back_populates="client")


class Master(Base):
    __tablename__ = "masters"

    id: Mapped[int] = mapped_column(primary_key=True)
    tg_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, nullable=True)  # для адмін-нотифікацій
    auth_code: Mapped[str | None] = mapped_column(String(32), unique=True, nullable=True)  # код для /master <код>
    full_name: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(default=True)

    working_hours: Mapped[list["WorkingHours"]] = relationship(back_populates="master", cascade="all, delete-orphan")
    days_off: Mapped[list["DayOff"]] = relationship(back_populates="master", cascade="all, delete-orphan")
    services: Mapped[list["MasterService"]] = relationship(back_populates="master", cascade="all, delete-orphan")
    bookings: Mapped[list["Booking"]] = relationship(back_populates="master")


class Service(Base):
    """Каталог послуг (напр. 'Манікюр класичний', 'Покриття гель-лак')."""

    __tablename__ = "services"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(default=True)

    masters: Mapped[list["MasterService"]] = relationship(back_populates="service", cascade="all, delete-orphan")


class MasterService(Base):
    """Зв'язок майстер<->послуга з ціною і тривалістю саме в цього майстра."""

    __tablename__ = "master_services"
    __table_args__ = (UniqueConstraint("master_id", "service_id", name="uq_master_service"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    master_id: Mapped[int] = mapped_column(ForeignKey("masters.id", ondelete="CASCADE"))
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id", ondelete="CASCADE"))
    duration_min: Mapped[int] = mapped_column(SmallInteger)
    price: Mapped[float] = mapped_column(Numeric(10, 2))
    buffer_min: Mapped[int] = mapped_column(SmallInteger, default=0)

    master: Mapped["Master"] = relationship(back_populates="services")
    service: Mapped["Service"] = relationship(back_populates="masters")


class WorkingHours(Base):
    """Робочі години майстра по днях тижня (0=понеділок ... 6=неділя)."""

    __tablename__ = "working_hours"
    # Один день може мати кілька інтервалів, напр. 09:00-13:00 і 14:00-18:00.
    __table_args__ = (
        UniqueConstraint(
            "master_id", "weekday", "start_time", "end_time", name="uq_master_weekday_interval"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    master_id: Mapped[int] = mapped_column(ForeignKey("masters.id", ondelete="CASCADE"))
    weekday: Mapped[int] = mapped_column(SmallInteger)  # 0-6
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)

    master: Mapped["Master"] = relationship(back_populates="working_hours")


class DayOff(Base):
    """Точкові вихідні / відпустки / лікарняні майстра."""

    __tablename__ = "days_off"
    __table_args__ = (UniqueConstraint("master_id", "date", name="uq_master_dayoff"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    master_id: Mapped[int] = mapped_column(ForeignKey("masters.id", ondelete="CASCADE"))
    date: Mapped[date] = mapped_column(Date)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    master: Mapped["Master"] = relationship(back_populates="days_off")


class Booking(Base):
    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"))
    master_id: Mapped[int] = mapped_column(ForeignKey("masters.id", ondelete="CASCADE"))
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"))

    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    status: Mapped[BookingStatus] = mapped_column(
        Enum(BookingStatus, name="booking_status"), default=BookingStatus.confirmed
    )
    reminder_sent: Mapped[bool] = mapped_column(default=False)
    price_snapshot: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # lazy="selectin" — зв'язані об'єкти підтягуються одразу разом із бронюванням.
    # Для async-сесії це обов'язково: ліниве підвантаження (типове lazy="select")
    # поза greenlet-контекстом падає з MissingGreenlet — саме так ламався перегляд
    # і скасування записів (обробники читають booking.client.full_name).
    client: Mapped["Client"] = relationship(back_populates="bookings", lazy="selectin")
    master: Mapped["Master"] = relationship(back_populates="bookings", lazy="selectin")
    service: Mapped["Service"] = relationship(lazy="selectin")


class Broadcast(Base):
    """Розсилка клієнтам: текст + період повтору у днях.

    Одержувачі — усі клієнти (users бота), окрім майстрів і власника;
    графік рахується від останнього не скасованого візиту кожного клієнта
    (див. app/services/broadcast.py).
    """

    __tablename__ = "broadcasts"

    id: Mapped[int] = mapped_column(primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    interval_days: Mapped[int] = mapped_column(SmallInteger, default=15)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BroadcastSend(Base):
    """Факт надсилання розсилки конкретному клієнту — точка відліку графіку."""

    __tablename__ = "broadcast_sends"
    __table_args__ = (
        UniqueConstraint("broadcast_id", "client_id", "sent_at", name="uq_broadcast_send"),
        # індекс під каскадне видалення клієнта (див. міграцію 0003)
        Index("ix_broadcast_sends_client", "client_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    broadcast_id: Mapped[int] = mapped_column(ForeignKey("broadcasts.id", ondelete="CASCADE"))
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"))
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)

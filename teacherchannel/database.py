from __future__ import annotations

from typing import List, Optional

from sqlalchemy import BigInteger, Column, ForeignKey, or_, and_, PrimaryKeyConstraint
from sqlalchemy.orm import relationship

from pie.database import database, session


class TeacherChannel(database.base):
    """Subject channels containing teacher channel, synced from the original channel."""

    __tablename__ = "school_teacherchannel_teacherchannel"

    guild_id = Column(BigInteger)
    master_id = Column(BigInteger, unique=True)
    slave_id = Column(BigInteger, primary_key=True, autoincrement=False)
    teachers = relationship(
        lambda: Teacher, cascade="all, delete-orphan", back_populates="teacherchannel"
    )

    @staticmethod
    def get(guild_id: int, channel_id: int) -> Optional[TeacherChannel]:
        return (
            session.query(TeacherChannel)
            .filter(
                and_(
                    or_(
                        TeacherChannel.master_id == channel_id,
                        TeacherChannel.slave_id == channel_id,
                    ),
                    TeacherChannel.guild_id == guild_id,
                )
            )
            .one_or_none()
        )

    @staticmethod
    def get_all(guild_id: int) -> List[TeacherChannel]:
        return session.query(TeacherChannel).filter_by(guild_id=guild_id).all()

    @staticmethod
    def get_guild_ids() -> List[int]:
        return [
            t.guild_id
            for t in session.query(TeacherChannel.guild_id)
            .distinct(TeacherChannel.guild_id)
            .all()
        ]

    @staticmethod
    def add_channel(
        guild_id: int, master_id: int, slave_id: int
    ) -> Optional[TeacherChannel]:
        channel = TeacherChannel.get(guild_id, master_id)
        if channel is not None:
            return None
        channel = TeacherChannel(
            guild_id=guild_id, master_id=master_id, slave_id=slave_id
        )
        session.add(channel)
        session.commit()
        return channel

    @staticmethod
    def add_teacher(
        guild_id: int, channel_id: int, teacher_id: int
    ) -> Optional[TeacherChannel]:
        channel = TeacherChannel.get(guild_id, channel_id)
        if not channel:
            return None
        if teacher_id in [t.user_id for t in channel.teachers]:
            return None
        channel.teachers.append(Teacher(user_id=teacher_id))
        session.merge(channel)
        session.commit()
        return channel

    def remove_channel(self) -> None:
        session.delete(self)
        session.commit()

    @staticmethod
    def remove_teacher(guild_id: int, channel_id: int, teacher_id: int) -> bool:
        channel = TeacherChannel.get(guild_id, channel_id)
        if not channel:
            return False
        teacher_to_remove = Teacher.get(channel.slave_id, teacher_id)
        try:
            channel.teachers.remove(teacher_to_remove)
        except ValueError:
            return False
        session.merge(channel)
        session.commit()
        return True

    def __repr__(self) -> str:
        return (
            f"<TeacherChannel guild_id='{self.guild_id}' "
            f"slave_id='{self.slave_id}' master_id='{self.master_id}' "
            f"teachers=[{'; '.join([str(t.user_id) for t in self.teachers])}]>"
        )

    def dump(self) -> dict:
        return {
            "guild_id": self.guild_id,
            "slave_id": self.slave_id,
            "master_id": self.master_id,
            "teachers": [t.user_id for t in self.teachers],
        }


class Teacher(database.base):
    """Teachers of a channel"""

    __tablename__ = "school_teacherchannel_teacher"

    user_id = Column(BigInteger)
    slave_id = Column(
        BigInteger,
        ForeignKey("school_teacherchannel_teacherchannel.slave_id", ondelete="CASCADE"),
    )
    teacherchannel = relationship("TeacherChannel", back_populates="teachers")
    # composite primary key
    __table_args__ = (PrimaryKeyConstraint("user_id", "slave_id"),)

    @staticmethod
    def get(slave_id: int, teacher_id: int) -> Optional[Teacher]:
        return (
            session.query(Teacher)
            .filter_by(user_id=teacher_id, slave_id=slave_id)
            .one_or_none()
        )

    def __repr__(self):
        return f"<Teacher user_id='{self.user_id}' " f"slave_id='{self.slave_id}'>"

    def dump(self) -> dict:
        return {
            "user_id": self.user_id,
            "slave_id": self.slave_id,
        }

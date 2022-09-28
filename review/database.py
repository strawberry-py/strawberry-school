from __future__ import annotations

from datetime import date, timedelta

import discord

from discord.ext import commands

from sqlalchemy import (
    BigInteger,
    Column,
    Integer,
    String,
    Boolean,
    Date,
    ForeignKey,
    UniqueConstraint,
    select,
    func,
)

from sqlalchemy.orm import relationship, column_property

from pie.database import database, session
from typing import List, Optional, Union

from ..school.database import Subject, Teacher


class SubjectRelevance(database.base):
    """Holds user votes for subject reviews.

    Args:
        voter_id: User's Discord ID
        vote: True if positive, False if negative
        review: SubjectReview IDX
    """

    __tablename__ = "school_review_subject_relevance"

    voter_id = Column(BigInteger, primary_key=True)
    vote = Column(Boolean, default=False)
    review = Column(
        Integer,
        ForeignKey("school_review_subject_review.idx", ondelete="CASCADE"),
        primary_key=True,
    )

    @staticmethod
    def reset(review_id: int):
        result = session.query(SubjectRelevance).filter_by(review=review_id).delete()
        session.commit()
        return result

    def __repr__(self) -> str:
        return (
            f'<{self.__class__.__name__} voter_id="{self.voter_id}" vote="{self.vote}" '
            f'review="{self.review}">'
        )

    def dump(self) -> dict:
        return {
            "voter_id": self.voter_id,
            "vote": self.vote,
            "review": self.review,
        }


class SubjectReview(database.base):
    """Holds information about subject reviews and all the logic.

    Args:
        idx: Unique review ID
        guild_id: Guild ID
        author_id: Author's Discord ID
        anonym: Show or hide author name
        subject_id: IDX of Subject
        grade: Grade as in school (should be 1-5)
        text_review: Text of review
        created: Date of creation
        updated: Date of update
        subject: Relationship with Subject
        guarantor: Relationship with Teacher (subject guarantor)
        relevance: Relationship with Votes (SubjectRelevance)
        upvotes: Count of positive votes
        downvotes: Count of negative votes
    """

    __tablename__ = "school_review_subject_review"
    __table_args__ = (
        UniqueConstraint(
            "author_id",
            "guild_id",
            "subject_id",
            name="guild_id_author_id_subject_id_unique",
        ),
    )

    idx = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger)
    author_id = Column(BigInteger)
    anonym = Column(Boolean, default=True)
    subject_id = Column(
        Integer, ForeignKey("school_dataset_subject.idx", ondelete="CASCADE")
    )
    guarantor_id = Column(
        Integer, ForeignKey("school_dataset_teacher.idx", ondelete="SET NULL")
    )
    grade = Column(Integer, default=0)
    text_review = Column(String, default=None)
    created = Column(Date)
    updated = Column(Date)
    subject = relationship("Subject")
    guarantor = relationship(lambda: Teacher)
    relevance = relationship("SubjectRelevance", cascade="all, delete-orphan, delete")

    upvotes = column_property(
        select([func.count(SubjectRelevance.voter_id)])
        .where(SubjectRelevance.review == idx)
        .where(SubjectRelevance.vote.is_(True))
        .scalar_subquery()
    )
    downvotes = column_property(
        select([func.count(SubjectRelevance.voter_id)])
        .where(SubjectRelevance.review == idx)
        .where(SubjectRelevance.vote.is_(False))
        .scalar_subquery()
    )

    def vote(self, user: Union[discord.User, discord.Member], vote: Optional[bool]):
        """Add or edit user's vote

        Args:
            user: Voting Discord user
            vote: True if upvote, False if downvote, None if delete
        """
        db_vote = (
            session.query(SubjectRelevance)
            .filter_by(review=self.idx)
            .filter_by(voter_id=user.id)
            .one_or_none()
        )

        if vote is None:
            if not db_vote:
                return

            session.delete(db_vote)
            session.commit()
            return

        if not db_vote:
            db_vote = SubjectRelevance(review=self.idx, voter_id=user.id)

        db_vote.vote = vote

        session.merge(db_vote)
        session.commit()

    def edit(self, grade: int, anonym: bool, text: str):
        """Edit review information. Reset relevance for reviews
        lastly edited before 1 month."""
        if (date.today() - self.updated) > timedelta(days=30):
            SubjectRelevance.reset(self.idx)

        self.grade = grade
        self.anonym = anonym
        self.text_review = text
        self.updated = date.today()
        self.guarantor_id = self.subject.guarantor_id

        session.commit()

    def delete(self):
        """Delete review"""
        session.delete(self)
        session.commit()

    @staticmethod
    def avg_grade(subject: Subject) -> int:
        """Get average grade of subject"""
        query = session.query(func.avg(SubjectReview.grade)).filter(
            SubjectReview.subject_id == subject.idx
        )

        return query.scalar()

    @staticmethod
    def add(
        ctx: commands.Context, subject: Subject, grade: int, anonym: bool, text: str
    ) -> SubjectReview:
        """Add review information"""
        now = date.today()
        review = SubjectReview(
            guild_id=ctx.guild.id,
            author_id=ctx.author.id,
            anonym=anonym,
            subject_id=subject.idx,
            guarantor_id=subject.guarantor_id,
            grade=grade,
            text_review=text,
            updated=now,
            created=now,
        )

        session.add(review)
        session.commit()

        return review

    @staticmethod
    def get_member_review(
        member: discord.Member, subject: Subject
    ) -> Optional[SubjectReview]:
        """Get members subject review"""
        query = (
            session.query(SubjectReview)
            .filter_by(author_id=member.id)
            .filter_by(subject_id=subject.idx)
        )

        return query.one_or_none()

    @staticmethod
    def get_all_by_author(ctx: commands.Context) -> List[SubjectReview]:
        """Get all user's reviews"""
        query = session.query(SubjectReview).filter_by(author_id=ctx.author.id).all()

        return query

    @staticmethod
    def get_all_by_subject(subject: Subject) -> List[SubjectReview]:
        """Get all subject's reviews"""
        query = (
            session.query(SubjectReview)
            .filter_by(subject_id=subject.idx)
            .order_by(
                SubjectReview.upvotes - SubjectReview.downvotes,
                SubjectReview.updated.desc(),
            )
            .all()
        )

        return query

    @staticmethod
    def get_by_idx(ctx: commands.Context, idx: int) -> Optional[SubjectReview]:
        """Get review by it's IDX"""
        query = (
            session.query(SubjectReview)
            .filter_by(guild_id=ctx.guild.id)
            .filter_by(idx=idx)
        )

        return query.one_or_none()

    def __repr__(self) -> str:
        return (
            f'<{self.__class__.__name__} idx="{self.idx}" guild_id="{self.guild_id}" '
            f'author_id="{self.author_id}" anonym="{self.anonym}" '
            f'subject_id="{self.subject_id}" guarantor_id={self.guarantor_id}" '
            f'grade="{self.grade}", text_review="{self.text_review}" created="{self.created}" '
            f'updated="{self.updated}" upvotes="{self.upvotes}" downvotes="{self.downvotes}">'
        )

    def dump(self) -> dict:
        return {
            "idx": self.idx,
            "guild_id": self.guild_id,
            "author_id": self.author_id,
            "anonym": self.anonym,
            "subject_id": self.subject_id,
            "guarantor_id": self.guarantor_id,
            "grade": self.grade,
            "text_review": self.text_review,
            "created": self.created,
            "updated": self.updated,
            "upvotes": self.upvotes,
            "downvotes": self.downvotes,
            "relevance": self.relevance,
        }


class TeacherRelevance(database.base):
    """Holds user votes for teacher reviews.

    Args:
        voter_id: User's Discord ID
        vote: True if positive, False if negative
        review: Teacher review IDX
    """

    __tablename__ = "school_review_teacher_relevance"

    voter_id = Column(BigInteger, primary_key=True)
    vote = Column(Boolean, default=False)
    review = Column(
        Integer,
        ForeignKey("school_review_teacher_review.idx", ondelete="CASCADE"),
        primary_key=True,
    )

    @staticmethod
    def reset(review_id: int):
        result = session.query(TeacherRelevance).filter_by(review=review_id).delete()
        session.commit()
        return result

    def __repr__(self) -> str:
        return (
            f'<{self.__class__.__name__} voter_id="{self.voter_id}" vote="{self.vote}" '
            f'review="{self.review}">'
        )

    def dump(self) -> dict:
        return {
            "voter_id": self.voter_id,
            "vote": self.vote,
            "review": self.review,
        }


class TeacherReview(database.base):
    """Holds information about teacher reviews and all the logic.

    Args:
        idx: Unique review ID
        guild_id: Guild ID
        author_id: Author's Discord ID
        anonym: Show or hide author name
        teacher_id: IDX of Teacher
        grade: Grade as in school (should be 1-5)
        text_review: Text of review
        created: Date of creation
        updated: Date of update
        teacher: Relationship with Teacher
        relevance: Relationship with Votes (TeacherRelevance)
        upvotes: Count of positive votes
        downvotes: Count of negative votes
    """

    __tablename__ = "school_review_teacher_review"
    __table_args__ = (
        UniqueConstraint(
            "author_id",
            "guild_id",
            "teacher_id",
            name="guild_id_author_id_teacher_id_unique",
        ),
    )

    idx = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger)
    author_id = Column(BigInteger)
    anonym = Column(Boolean, default=True)
    teacher_id = Column(
        Integer, ForeignKey("school_dataset_teacher.idx", ondelete="CASCADE")
    )
    grade = Column(Integer, default=0)
    text_review = Column(String, default=None)
    created = Column(Date)
    updated = Column(Date)
    teacher = relationship(lambda: Teacher)
    relevance = relationship("TeacherRelevance", cascade="all, delete-orphan, delete")

    upvotes = column_property(
        select([func.count(TeacherRelevance.voter_id)])
        .where(TeacherRelevance.review == idx)
        .where(TeacherRelevance.vote.is_(True))
        .scalar_subquery()
    )
    downvotes = column_property(
        select([func.count(TeacherRelevance.voter_id)])
        .where(TeacherRelevance.review == idx)
        .where(TeacherRelevance.vote.is_(False))
        .scalar_subquery()
    )

    def vote(self, user: Union[discord.User, discord.Member], vote: Optional[bool]):
        """Add or edit user's vote

        Args:
            user: Voting Discord user
            vote: True if upvote, False if downvote, None if delete
        """
        db_vote = (
            session.query(TeacherRelevance)
            .filter_by(review=self.idx)
            .filter_by(voter_id=user.id)
            .one_or_none()
        )

        if vote is None:
            if not db_vote:
                return

            session.delete(db_vote)
            session.commit()
            return

        if not db_vote:
            db_vote = TeacherRelevance(review=self.idx, voter_id=user.id)

        db_vote.vote = vote

        session.merge(db_vote)
        session.commit()

    def edit(self, grade: int, anonym: bool, text: str):
        """Edit review information. Reset relevance for reviews
        lastly edited before 1 month."""
        if (date.today() - self.updated) > timedelta(days=30):
            TeacherRelevance.reset(self.idx)

        self.grade = grade
        self.anonym = anonym
        self.text_review = text
        self.updated = date.today()

        session.commit()

    def delete(self):
        """Delete review"""
        session.delete(self)
        session.commit()

    @staticmethod
    def avg_grade(teacher: Teacher) -> int:
        """Get average grade of teacher"""
        query = session.query(func.avg(TeacherReview.grade)).filter(
            TeacherReview.teacher_id == teacher.idx
        )

        return query.scalar()

    @staticmethod
    def add(
        ctx: commands.Context, teacher: Teacher, grade: int, anonym: bool, text: str
    ) -> TeacherReview:
        """Add review information"""
        now = date.today()
        review = TeacherReview(
            guild_id=ctx.guild.id,
            author_id=ctx.author.id,
            anonym=anonym,
            teacher_id=teacher.idx,
            grade=grade,
            text_review=text,
            updated=now,
            created=now,
        )

        session.add(review)
        session.commit()

        return review

    @staticmethod
    def get_member_review(
        member: discord.Member, teacher: Teacher
    ) -> Optional[TeacherReview]:
        """Get members teacher review"""
        query = (
            session.query(TeacherReview)
            .filter_by(author_id=member.id)
            .filter_by(teacher_id=teacher.idx)
        )

        return query.one_or_none()

    @staticmethod
    def get_all_by_author(ctx: commands.Context) -> List[TeacherReview]:
        """Get all user's reviews"""
        query = session.query(TeacherReview).filter_by(author_id=ctx.author.id).all()

        return query

    @staticmethod
    def get_all_by_teacher(teacher: Teacher) -> List[TeacherReview]:
        """Get all subject's reviews"""
        query = (
            session.query(TeacherReview)
            .filter_by(teacher_id=teacher.idx)
            .order_by(
                TeacherReview.upvotes - TeacherReview.downvotes,
                TeacherReview.updated.desc(),
            )
            .all()
        )

        return query

    @staticmethod
    def get_by_idx(ctx: commands.Context, idx: int) -> Optional[TeacherReview]:
        """Get review by it's IDX"""
        query = (
            session.query(TeacherReview)
            .filter_by(guild_id=ctx.guild.id)
            .filter_by(idx=idx)
        )

        return query.one_or_none()

    def __repr__(self) -> str:
        return (
            f'<{self.__class__.__name__} idx="{self.idx}" guild_id="{self.guild_id}" '
            f'author_id="{self.author_id}" anonym="{self.anonym}" teacher_id="{self.teacher_id}" '
            f'grade="{self.grade}", text_review="{self.text_review}" created="{self.created}" '
            f'updated="{self.updated}" upvotes="{self.upvotes}" downvotes="{self.downvotes}">'
        )

    def dump(self) -> dict:
        return {
            "idx": self.idx,
            "guild_id": self.guild_id,
            "author_id": self.author_id,
            "anonym": self.anonym,
            "teacher_id": self.teacher_id,
            "grade": self.grade,
            "text_review": self.text_review,
            "created": self.created,
            "updated": self.updated,
            "upvotes": self.upvotes,
            "downvotes": self.downvotes,
            "relevance": self.relevance,
        }

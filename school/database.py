from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Column,
    Integer,
    String,
    ForeignKey,
    Table,
    UniqueConstraint,
    not_,
)
from sqlalchemy.orm import relationship
from typing import Callable, Dict, List, Optional

from pie.database import database, session

teachers_subjects = Table(
    "school_dataset_teachers_subjects",
    database.base.metadata,
    Column(
        "subject",
        ForeignKey("school_dataset_subject.idx", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "teacher",
        ForeignKey("school_dataset_teacher.idx", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class SubjectProgram(database.base):
    __tablename__ = "school_dataset_subject_program"

    subject_idx = Column(
        ForeignKey("school_dataset_subject.idx", ondelete="CASCADE"),
        primary_key=True,
    )
    program_idx = Column(
        ForeignKey("school_dataset_program.idx", ondelete="CASCADE"),
        primary_key=True,
    )
    year = Column(Integer, primary_key=True)
    obligation = Column(String, primary_key=True)
    subject = relationship("Subject", back_populates="programs")
    program = relationship("Program", back_populates="subjects")

    @staticmethod
    def get(subject: Subject, program: Program, year: int, obligation: str):
        query = (
            session.query(SubjectProgram)
            .filter_by(subject_idx=subject.idx)
            .filter_by(program_idx=program.idx)
            .filter_by(year=year)
            .filter_by(obligation=obligation)
            .one_or_none()
        )

        return query

    @staticmethod
    def add_relation(subject: Subject, program: Program, year: int, obligation: str):
        relation = SubjectProgram(
            subject_idx=subject.idx,
            program_idx=program.idx,
            year=year,
            obligation=obligation,
        )

        session.add(relation)
        session.commit()

        return relation

    def delete(self):
        session.delete(self)
        session.commit()


class Teacher(database.base):
    __tablename__ = "school_dataset_teacher"
    __table_args__ = (
        UniqueConstraint("school_id", "guild_id", name="school_id_guild_id_unique"),
    )

    idx = Column(Integer, primary_key=True)
    school_id = Column(Integer)
    guild_id = Column(BigInteger)
    name = Column(String)
    subjects = relationship(
        "Subject",
        secondary=teachers_subjects,
        back_populates="teachers",
    )
    guaranted_subjects = relationship(
        "Subject",
        back_populates="guarantor",
    )

    _used_filter_generators = []
    _is_used_checks = []

    @staticmethod
    def add_used_filter_generator(func: Callable):
        """Add callable to list of functions which are called
        to get filter of used teacher.

        The function must return filter statement, for example:

        `stmt = exists().where(Teacher.idx==MyDatabaseObject.foreign_teacher_id)`

        """
        if func is None:
            return

        if func not in Teacher._used_filter_generators:
            Teacher._used_filter_generators.append(func)

    @staticmethod
    def add_is_used_check(func: Callable):
        """Add callable to list of functions which are called
        to check if teacher is in use somewhere.

        The function must return bool.
        """
        if func is None:
            return

        if func not in Teacher._is_used_checks:
            Teacher._is_used_checks.append(func)

    @staticmethod
    def get_by_sid(ctx, school_id: int) -> Optional[Teacher]:
        query = (
            session.query(Teacher)
            .filter_by(guild_id=ctx.guild.id)
            .filter_by(school_id=school_id)
        )

        return query.one_or_none()

    @staticmethod
    def search(ctx, name: str) -> List[Teacher]:
        name = name.replace("%", "")
        query = (
            session.query(Teacher)
            .filter_by(guild_id=ctx.guild.id)
            .filter(Teacher.name.ilike(f"%{name}%"))
        )
        return query.all()

    @staticmethod
    def get_or_create(ctx, school_id: int, name: str) -> Teacher:
        query = (
            session.query(Teacher)
            .filter_by(school_id=school_id, guild_id=ctx.guild.id)
            .one_or_none()
        )

        if query:
            return query

        teacher = Teacher(school_id=school_id, name=name, guild_id=ctx.guild.id)

        session.add(teacher)
        session.commit()

        return teacher

    @staticmethod
    def purge(ctx):
        """BEWARE! Purges all teachers that are not used!"""

        query = session.query(Teacher).filter_by(guild_id=ctx.guild.id)

        for func in Teacher._used_filter_generators:
            query = query.filter(not_(func()))

        query.delete(synchronize_session="fetch")

        session.commit()

    @staticmethod
    def get_not_used(ctx) -> List[Teacher]:
        query = session.query(Teacher).filter_by(guild_id=ctx.guild.id)

        for func in Teacher._used_filter_generators:
            query = query.filter(not_(func()))

        return query.all()

    def edit(self, name):
        if name:
            self.name = name
        session.commit()

    def is_used(self) -> bool:
        for func in Teacher._is_used_checks:
            if func(self):
                return True

        return False

    def delete(self):
        session.delete(self)
        session.commit()

    def __repr__(self) -> str:
        return (
            f'<{self.__class__.__name__} idx="{self.idx}" school_id="{self.school_id}"'
            f'guild_id="{self.guild_id}" name="{self.name}">'
        )

    def dump(self) -> dict:
        return {
            "idx": self.id,
            "schoold_id": self.school_id,
            "guild_id": self.guild_id,
            "name": self.name,
            "subjects": self.subjects,
        }


class Program(database.base):
    __tablename__ = "school_dataset_program"
    __table_args__ = (
        UniqueConstraint(
            "guild_id",
            "abbreviation",
            "degree",
            name="guild_id_abbreviation_degree_unique",
        ),
    )

    idx = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger)
    abbreviation = Column(String)
    name = Column(String)
    degree = Column(String)
    subjects = relationship(
        "SubjectProgram",
        back_populates="program",
        cascade="all, delete-orphan, delete",
    )

    @staticmethod
    def get_by_abbreviation(ctx, degree: str, abbreviation: str) -> Optional[Program]:
        query = (
            session.query(Program)
            .filter_by(guild_id=ctx.guild.id)
            .filter_by(abbreviation=abbreviation)
            .filter(Program.degree.like(f"{degree}%"))
        )

        return query.one_or_none()

    def edit(self, abbreviation, name, degree):
        if abbreviation:
            self.abbreviation = abbreviation
        if name:
            self.name = name
        if degree:
            self.degree = degree

        session.commit()

    def get_all(ctx, degree: str) -> List[Program]:
        query = session.query(Program).filter_by(guild_id=ctx.guild.id)

        if degree:
            degree = degree.upper()
            query = query.filter(Program.degree.like(f"{degree}%"))

        return query.all()

    def get_or_create(ctx, abbreviation: str, degree: str) -> Program:
        query = (
            session.query(Program)
            .filter_by(guild_id=ctx.guild.id, abbreviation=abbreviation, degree=degree)
            .one_or_none()
        )

        if query:
            return query

        program = Program(
            guild_id=ctx.guild.id, abbreviation=abbreviation, degree=degree
        )

        session.add(program)
        session.commit()

        return program

    def delete(self):
        session.delete(self)
        session.commit()

    def __repr__(self) -> str:
        return (
            f'<{self.__class__.__name__} idx="{self.idx}" guild_id="{self.guild_id}" '
            f'abbreviation="{self.abbreviation}" name="{self.name}" degree="{self.degree}">'
        )

    def dump(self) -> dict:
        return {
            "idx": self.id,
            "guild_id": self.guild_id,
            "abbreviation": self.abbreviation,
            "name": self.name,
            "degree": self.degree,
            "subjects": self.subjects,
        }


class SubjectUrl(database.base):
    __tablename__ = "school_dataset_subject_url"

    subject_id = Column(
        Integer,
        ForeignKey("school_dataset_subject.idx", ondelete="CASCADE"),
        primary_key=True,
    )
    url = Column(String, primary_key=True)
    subject = relationship("Subject", back_populates="url")

    def __repr__(self) -> str:
        return f'<{self.__class__.__name__} subject_ixd="{self.subject_ixd}" url="{self.url}">'

    def dump(self) -> dict:
        return {
            "subject_ixd": self.subject_ixd,
            "url": self.url,
        }


class Subject(database.base):
    __tablename__ = "school_dataset_subject"
    __table_args__ = (
        UniqueConstraint(
            "abbreviation", "guild_id", name="abbreviation_guild_id_unique"
        ),
    )

    idx = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger)
    abbreviation = Column(String)
    name = Column(String)
    institute = Column(String)
    semester = Column(String)
    guarantor_id = Column(
        Integer, ForeignKey("school_dataset_teacher.idx", ondelete="SET NULL")
    )
    guarantor = relationship(
        lambda: Teacher,
        back_populates="guaranted_subjects",
    )
    teachers = relationship(
        lambda: Teacher,
        secondary=teachers_subjects,
        back_populates="subjects",
    )
    programs = relationship(
        "SubjectProgram", back_populates="subject", cascade="all, delete-orphan, delete"
    )
    url = relationship(
        "SubjectUrl", back_populates="subject", cascade="all, delete-orphan, delete"
    )

    _used_filter_generators = []
    _is_used_checks = []

    @staticmethod
    def add_used_filter_generator(func: Callable):
        """Add callable to list of functions which are called
        to get filter of used subjects.

        The function must return filter statement, for example:

        `stmt = exists().where(Subject.idx==MyDatabaseObject.foreign_teacher_id)`

        """
        if func is None:
            return

        if func not in Subject._used_filter_generators:
            Subject._used_filter_generators.append(func)

    @staticmethod
    def add_is_used_check(func: Callable):
        """Add callable to list of functions which are called
        to check if subject is in use somewhere.

        The function must return bool.
        """
        if func is None:
            return

        if func not in Subject._is_used_checks:
            Subject._is_used_checks.append(func)

    @staticmethod
    def get_not_used(ctx) -> List[Subject]:
        query = session.query(Subject).filter_by(guild_id=ctx.guild.id)

        for func in Subject._used_filter_generators:
            query = query.filter(not_(func()))

        return query.all()

    @staticmethod
    def purge(ctx):
        """BEWARE! Purges all subjects that are not used!"""

        query = session.query(Subject).filter_by(guild_id=ctx.guild.id)

        for func in Subject._used_filter_generators:
            query = query.filter(not_(func()))

        query.delete(synchronize_session="fetch")

        session.commit()

    @staticmethod
    def search(ctx, name: str) -> List[Subject]:
        name = name.replace("%", "")
        query = (
            session.query(Subject)
            .filter_by(guild_id=ctx.guild.id)
            .filter(Subject.name.ilike(f"%{name}%"))
        )
        return query.all()

    @staticmethod
    def get_by_abbreviation(ctx, abbreviation: str) -> Optional[Subject]:
        query = (
            session.query(Subject)
            .filter_by(guild_id=ctx.guild.id)
            .filter_by(abbreviation=abbreviation.upper())
        )

        return query.one_or_none()

    @staticmethod
    def from_json(ctx, json_data):
        abbreviation = json_data.get("abbreviation", None)

        if not abbreviation:
            return None

        subject = (
            session.query(Subject)
            .filter_by(abbreviation=abbreviation, guild_id=ctx.guild.id)
            .one_or_none()
        )

        if not subject:
            subject = Subject(
                guild_id=ctx.guild.id,
                abbreviation=abbreviation,
            )

        name = json_data.get("name", None)
        institute = json_data.get("institute", None)
        winter_semester = json_data.get("winter_semester", False)
        summer_semester = json_data.get("summer_semester", False)

        if winter_semester and summer_semester:
            semester = "Both"
        elif winter_semester:
            semester = "Winter"
        else:
            semester = "Summer"

        subject.name = name
        subject.institute = institute
        subject.semester = semester

        session.merge(subject)
        session.flush()

        query = session.query(SubjectUrl).filter_by(subject_id=subject.idx).all()
        for relation in query:
            session.delete(relation)

        json_url = json_data.get("link", None)

        for url_str in json_url:
            subject.url.append(SubjectUrl(subject_id=subject.idx, url=url_str))

        session.commit()

        return subject

    def is_used(self) -> bool:
        for func in Subject._is_used_checks:
            if func(self):
                return True

        return False

    def delete(self):
        session.delete(self)
        session.commit()

    def edit(self, abbreviation, name, institute, semester, guarantor):
        if abbreviation:
            self.abbreviation = abbreviation
        if name:
            self.name = name
        if institute:
            self.institute = institute
        if semester:
            self.semester = semester
        if guarantor:
            self.guarantor = guarantor

        session.commit()

    def set_guarantor(self, guarantor: Teacher):
        self.guarantor = guarantor[0] if len(guarantor) != 0 else None
        session.commit()

    def set_teachers(self, teachers: List[Teacher]):
        self.teachers = teachers
        session.commit()

    def add_teachers(self, teachers: List[Teacher]) -> List[str]:
        ignored = []
        for teacher in teachers:
            if teacher in self.teachers:
                ignored.append(str(teacher.school_id))
            else:
                self.teachers.append(teacher)

        session.commit()

        return ignored

    def remove_teachers(self, teachers: List[Teacher]) -> List[str]:
        ignored = []
        for teacher in teachers:
            if teacher not in self.teachers:
                ignored.append(str(teacher.school_id))
            else:
                self.teachers.remove(teacher)

        session.commit()

        return ignored

    def import_programs(self, ctx, programs: Dict):
        self.programs = []

        for program_data in programs:
            program = Program.get_or_create(
                ctx, program_data["abbreviation"], program_data["degree"]
            )
            sub_prog = SubjectProgram(
                year=program_data["year"], obligation=program_data["obligation"]
            )
            sub_prog.program = program
            self.programs.append(sub_prog)

        session.commit()

    def __repr__(self) -> str:
        return (
            f'<{self.__class__.__name__} idx="{self.idx}" guild_id="{self.guild_id}" '
            f'abbreviation="{self.abbreviation} name="{self.name}" institute="{self.institute}" '
            f'programs="{self.programs}" semester="{self.semester}" '
            f'guarantor="{self.guarantor}" teachers="{self.teachers}" url="{self.url}">'
        )

    def dump(self) -> dict:
        return {
            "idx": self.idx,
            "guild_id": self.guild_id,
            "name": self.name,
            "institute": self.institute,
            "programs": self.programs,
            "semester": self.semester,
            "guarantor": self.guarantor,
            "teachers": self.teachers,
            "url": self.url,
        }

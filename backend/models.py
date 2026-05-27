from sqlalchemy import Column, Integer, String, Text, Numeric, Boolean, ForeignKey, BigInteger, DateTime
from sqlalchemy.orm import relationship
from database import Base

class Party(Base):
    __tablename__ = "parties"
    id             = Column(Integer, primary_key=True)
    abbreviation   = Column(String(30), unique=True, nullable=False)
    full_name      = Column(String(200), nullable=False)
    color_hex      = Column(String(7), default="#CCCCCC")
    alliance       = Column(String(100))
    constituencies = relationship("Constituency", back_populates="winning_party")
    results        = relationship("Result", back_populates="party")
    summary        = relationship("PartySummary", back_populates="party", uselist=False)

class Constituency(Base):
    __tablename__ = "constituencies"
    id                 = Column(Integer, primary_key=True)
    const_no           = Column(Integer, unique=True, nullable=False)
    name               = Column(String(100), nullable=False)
    district           = Column(String(100))
    region             = Column(String(50))
    total_electors     = Column(Integer)
    total_votes_polled = Column(Integer)
    total_evm_votes    = Column(Integer)
    total_postal_votes = Column(Integer)
    voter_turnout_pct  = Column(Numeric(5, 2))
    winning_party_id   = Column(Integer, ForeignKey("parties.id"))
    winning_candidate  = Column(String(150))
    winning_margin     = Column(Integer)
    eci_url            = Column(String(300))
    winning_party      = relationship("Party", back_populates="constituencies")
    results            = relationship("Result", back_populates="constituency")

class Result(Base):
    __tablename__ = "results"
    id              = Column(Integer, primary_key=True)
    constituency_id = Column(Integer, ForeignKey("constituencies.id"), nullable=False)
    party_id        = Column(Integer, ForeignKey("parties.id"))
    candidate_name  = Column(String(150), nullable=False)
    is_independent  = Column(Boolean, default=False)
    is_nota         = Column(Boolean, default=False)
    serial_no       = Column(Integer)
    evm_votes       = Column(Integer, default=0)
    postal_votes    = Column(Integer, default=0)
    vote_share_pct  = Column(Numeric(6, 3))
    is_winner       = Column(Boolean, default=False)
    constituency    = relationship("Constituency", back_populates="results")
    party           = relationship("Party", back_populates="results")
    profile         = relationship("CandidateProfile", back_populates="result", uselist=False)

class PartySummary(Base):
    __tablename__ = "party_summary"
    id                       = Column(Integer, primary_key=True)
    party_id                 = Column(Integer, ForeignKey("parties.id"), unique=True)
    seats_won                = Column(Integer, default=0)
    total_votes              = Column(BigInteger, default=0)
    overall_vote_share       = Column(Numeric(6, 3))
    constituencies_contested = Column(Integer, default=0)
    party                    = relationship("Party", back_populates="summary")

class CandidateProfile(Base):
    __tablename__ = "candidate_profiles"
    id                   = Column(Integer, primary_key=True)
    result_id            = Column(Integer, ForeignKey("results.id"))
    myneta_id            = Column(Integer)
    age                  = Column(Integer)
    gender               = Column(String)
    education            = Column(String)
    profession_self      = Column(String)
    profession_spouse    = Column(String)
    criminal_cases       = Column(Integer, default=0)
    criminal_details     = Column(Text)
    total_assets         = Column(BigInteger)
    total_liabilities    = Column(BigInteger)
    net_worth            = Column(BigInteger)
    source_url           = Column(String)
    scraped_at           = Column(DateTime(timezone=True))
    candidate_name_norm  = Column(String)
    constituency         = Column(String)
    result               = relationship("Result", back_populates="profile")

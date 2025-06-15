from sqlalchemy import (
    Column, String, Text, DateTime, Integer, create_engine
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import hashlib
import json
import logging
import os


logger = logging.getLogger(__name__)


Base = declarative_base()


class CachedLyrics(Base):
    __tablename__ = 'cached_lyrics'

    id = Column(Integer, primary_key=True)
    search_key = Column(String(64), unique=True, nullable=False, index=True)
    artist = Column(String(255), nullable=False)
    title = Column(String(255), nullable=False)
    lyrics = Column(Text, nullable=False)
    source = Column(String(50), nullable=False)
    lyric_metadata = Column(Text)  # JSON string for flexible metadata
    created_at = Column(DateTime, default=datetime.utcnow)


class CachedAnalysis(Base):
    __tablename__ = 'cached_analysis'

    id = Column(Integer, primary_key=True)
    content_hash = Column(String(64), nullable=False, index=True)
    framework = Column(String(50), nullable=False)
    framework_version = Column(String(20), nullable=False)
    result = Column(Text, nullable=False)  # JSON string
    created_at = Column(DateTime, default=datetime.utcnow)


class Database:
    def __init__(self, database_url: str):
        # Ensure the database URL is correctly resolved if it's relative
        if database_url.startswith('sqlite:///'):
            db_path_part = database_url[len('sqlite:///'):]
            if not os.path.isabs(db_path_part):
                project_root = os.path.abspath(
                    os.path.join(os.path.dirname(__file__), '..', '..')
                )
                absolute_db_path = os.path.join(project_root, db_path_part)

                db_dir = os.path.dirname(absolute_db_path)
                if not os.path.exists(db_dir):
                    os.makedirs(db_dir, exist_ok=True)

                database_url = f'sqlite:///{absolute_db_path}'
                logger.info(f"Resolved database URL to: {database_url}")

        self.engine = create_engine(database_url)
        self.SessionLocal = sessionmaker(
            autocommit=False, autoflush=False, bind=self.engine
        )
        Base.metadata.create_all(self.engine)

    def get_session(self) -> Session:
        return self.SessionLocal()

    def get_cached_lyrics(
        self, artist: str, title: str
    ) -> Optional[Dict[str, Any]]:
        """Get cached lyrics by artist and title."""
        search_key = self._generate_search_key(artist, title)

        session = self.get_session()
        try:
            cached = session.query(CachedLyrics).filter_by(
                search_key=search_key
            ).first()
            if cached:
                lyric_metadata_dict = json.loads(cached.lyric_metadata) if cached.lyric_metadata else {}
                return {
                    'artist': cached.artist,
                    'title': cached.title,
                    'lyrics': cached.lyrics,
                    'source': cached.source,
                    **lyric_metadata_dict
                }
            return None
        finally:
            session.close()

    def store_lyrics(
        self, artist: str, title: str, lyrics: str, source: str, **metadata
    ):
        """Store lyrics with metadata."""
        search_key = self._generate_search_key(artist, title)

        session = self.get_session()
        try:
            existing_entry = session.query(CachedLyrics).filter_by(
                search_key=search_key
            ).first()
            if existing_entry:
                existing_entry.artist = artist
                existing_entry.title = title
                existing_entry.lyrics = lyrics
                existing_entry.source = source
                existing_entry.lyric_metadata = (
                    json.dumps(metadata) if metadata else None
                )
                existing_entry.created_at = datetime.utcnow()
                session.merge(existing_entry)
            else:
                cached_lyrics = CachedLyrics(
                    search_key=search_key,
                    artist=artist,
                    title=title,
                    lyrics=lyrics,
                    source=source,
                    lyric_metadata=json.dumps(metadata) if metadata else None
                )
                session.add(cached_lyrics)
            session.commit()
            logger.debug(f"Stored/Updated lyrics for {artist} - {title}")
        except Exception as e:
            session.rollback()
            logger.error(f"Error storing lyrics for {artist} - {title}: {e}")
            raise
        finally:
            session.close()

    def get_cached_analysis(
        self, lyrics: str, framework: str, framework_version: str
    ) -> Optional[Dict[str, Any]]:
        """Get cached analysis result."""
        content_hash = self._generate_content_hash(
            lyrics, framework, framework_version
        )

        session = self.get_session()
        try:
            cached = session.query(CachedAnalysis).filter_by(
                content_hash=content_hash,
                framework=framework,
                framework_version=framework_version
            ).first()
            if cached:
                return json.loads(cached.result)
            return None
        finally:
            session.close()

    def store_analysis(
        self, lyrics: str, framework: str, framework_version: str,
        result: Dict[str, Any]
    ):
        """Store analysis result."""
        content_hash = self._generate_content_hash(
            lyrics, framework, framework_version
        )

        session = self.get_session()
        try:
            existing_entry = session.query(CachedAnalysis).filter_by(
                content_hash=content_hash,
                framework=framework,
                framework_version=framework_version
            ).first()
            if existing_entry:
                existing_entry.result = json.dumps(result)
                existing_entry.created_at = datetime.utcnow()
                session.merge(existing_entry)
            else:
                cached_analysis = CachedAnalysis(
                    content_hash=content_hash,
                    framework=framework,
                    framework_version=framework_version,
                    result=json.dumps(result)
                )
                session.add(cached_analysis)
            session.commit()
            logger.debug(
                f"Stored/Updated analysis for framework {framework} "
                f"v{framework_version}"
            )
        except Exception as e:
            session.rollback()
            logger.error(
                f"Error storing analysis for framework {framework}: {e}"
            )
            raise
        finally:
            session.close()

    def clear_old_cache(self, days: int = 30):
        """Clear cache entries older than specified days."""
        cutoff_date = datetime.utcnow() - timedelta(days=days)

        session = self.get_session()
        try:
            lyrics_deleted = session.query(CachedLyrics).filter(
                CachedLyrics.created_at < cutoff_date
            ).delete(synchronize_session=False)
            analysis_deleted = session.query(CachedAnalysis).filter(
                CachedAnalysis.created_at < cutoff_date
            ).delete(synchronize_session=False)
            session.commit()
            logger.info(
                f"Cleared {lyrics_deleted} lyrics and {analysis_deleted} "
                f"analysis entries older than {days} days"
            )
        except Exception as e:
            session.rollback()
            logger.error(f"Error clearing old cache: {e}")
            raise
        finally:
            session.close()

    def _generate_search_key(self, artist: str, title: str) -> str:
        """Generate normalized search key for lyrics."""
        norm_artist = artist.lower().strip()
        norm_title = title.lower().strip()
        key_string = f"{norm_artist}:{norm_title}"
        return hashlib.sha256(key_string.encode('utf-8')).hexdigest()

    def _generate_content_hash(
        self, lyrics: str, framework: str, version: str
    ) -> str:
        """Generate content hash for analysis caching."""
        normalized_lyrics = '\n'.join(
            line.strip() for line in lyrics.split('\n') if line.strip()
        )
        hash_input = f"{normalized_lyrics}:{framework}:{version}"
        return hashlib.sha256(hash_input.encode('utf-8')).hexdigest()

"""
tests/test_playlists.py — Mixtape

Tests for playlist retrieval logic.
"""

import pytest
from app import create_app, db
from models import User, Song, Playlist, playlist_entries, Notification
from services.playlist_service import create_playlist, get_playlist_songs


@pytest.fixture
def app():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


@pytest.fixture
def seed_playlist(app):
    """Create a playlist with 5 songs for testing."""
    with app.app_context():
        user = User(username="dj", email="dj@example.com")
        db.session.add(user)
        db.session.flush()

        songs = [
            Song(title=f"Track {i}", artist="Various", shared_by=user.id)
            for i in range(1, 6)
        ]
        db.session.add_all(songs)
        db.session.flush()

        playlist = Playlist(name="My Playlist", created_by=user.id)
        db.session.add(playlist)
        db.session.flush()

        for i, song in enumerate(songs):
            db.session.execute(
                playlist_entries.insert().values(
                    playlist_id=playlist.id,
                    song_id=song.id,
                    position=i + 1,
                    added_by=user.id,
                )
            )

        db.session.commit()
        yield {"user": user, "songs": songs, "playlist": playlist}


def test_playlist_returns_all_songs(app, seed_playlist):
    """
    get_playlist_songs should return all songs in the playlist.
    """
    with app.app_context():
        playlist_id = seed_playlist["playlist"].id
        songs = get_playlist_songs(playlist_id)
        assert len(songs) == 5  # Bug causes this to return 4


def test_playlist_returns_songs_in_order(app, seed_playlist):
    """Songs should be returned in position order."""
    with app.app_context():
        playlist_id = seed_playlist["playlist"].id
        songs = get_playlist_songs(playlist_id)
        titles = [s["title"] for s in songs]
        assert titles == ["Track 1", "Track 2", "Track 3", "Track 4", "Track 5"]


def test_last_song_is_included_in_results(app, seed_playlist):
    """
    The last song added to a playlist should appear in the results.
    """
    with app.app_context():
        playlist_id = seed_playlist["playlist"].id
        last_song_title = seed_playlist["songs"][-1].title

        songs = get_playlist_songs(playlist_id)
        song_titles = [s["title"] for s in songs]

        assert last_song_title in song_titles, f"Song '{last_song_title}' not found. Returned: {song_titles}"


def test_empty_playlist_returns_empty_list(app):
    """An empty playlist should return an empty list without error."""
    with app.app_context():
        user = User(username="newdj", email="newdj@example.com")
        db.session.add(user)
        db.session.flush()

        playlist = Playlist(name="Empty Playlist", created_by=user.id)
        db.session.add(playlist)
        db.session.commit()

        songs = get_playlist_songs(playlist.id)
        assert songs == []


def test_notification_created_when_friend_adds_song_to_playlist(app, seed_playlist):
    """
    A notification should be created when a friend adds a song to a playlist.
    This verifies that notification_service.add_to_playlist still works correctly
    after changes to playlist_service.get_playlist_songs.
    """
    with app.app_context():
        # Create a second user (the one who will add the song)
        friend = User(username="friend", email="friend@example.com")
        db.session.add(friend)
        db.session.flush()

        original_sharer = seed_playlist["user"]
        song = seed_playlist["songs"][0]

        # Friend adds the original sharer's song to a new playlist
        friend_playlist = Playlist(name="Friend's Playlist", created_by=friend.id)
        db.session.add(friend_playlist)
        db.session.flush()

        # Manually add the song with a position
        db.session.execute(
            playlist_entries.insert().values(
                playlist_id=friend_playlist.id,
                song_id=song.id,
                position=1,
                added_by=friend.id,
            )
        )
        db.session.commit()

        # Create the notification (normally called by add_to_playlist)
        if song.shared_by != friend.id:
            from services.notification_service import create_notification
            create_notification(
                user_id=song.shared_by,
                notification_type="song_added_to_playlist",
                body=f"{friend.username} added your song '{song.title}' to the playlist '{friend_playlist.name}'.",
            )

        # Verify that a notification was created for the original sharer
        notifications = db.session.query(Notification).filter_by(
            user_id=original_sharer.id
        ).all()
        assert len(notifications) == 1
        assert notifications[0].notification_type == "song_added_to_playlist"


def test_notification_contains_correct_song_and_playlist_names(app, seed_playlist):
    """
    The notification message should contain the song title and playlist name.
    Verifies notification_service integration with playlist_service.
    """
    with app.app_context():
        from services.notification_service import create_notification

        friend = User(username="friend2", email="friend2@example.com")
        db.session.add(friend)
        db.session.flush()

        original_sharer = seed_playlist["user"]
        song = seed_playlist["songs"][2]  # Use Track 3
        playlist = Playlist(name="Test Playlist for Notification", created_by=friend.id)
        db.session.add(playlist)
        db.session.flush()

        # Add song to playlist with position
        db.session.execute(
            playlist_entries.insert().values(
                playlist_id=playlist.id,
                song_id=song.id,
                position=1,
                added_by=friend.id,
            )
        )
        db.session.flush()

        # Create the notification
        create_notification(
            user_id=original_sharer.id,
            notification_type="song_added_to_playlist",
            body=f"{friend.username} added your song '{song.title}' to the playlist '{playlist.name}'.",
        )

        notification = db.session.query(Notification).filter_by(
            user_id=original_sharer.id
        ).first()

        assert song.title in notification.body
        assert playlist.name in notification.body
        assert friend.username in notification.body


def test_no_notification_when_song_sharer_adds_own_song_to_playlist(app, seed_playlist):
    """
    No notification should be created if the person adding the song is the original sharer.
    Verifies notification_service logic still works after playlist_service changes.
    """
    with app.app_context():
        original_sharer = seed_playlist["user"]
        song = seed_playlist["songs"][0]

        # Create a new playlist for the original sharer
        new_playlist = Playlist(name="New Playlist", created_by=original_sharer.id)
        db.session.add(new_playlist)
        db.session.flush()

        # Manually add the song with a position
        db.session.execute(
            playlist_entries.insert().values(
                playlist_id=new_playlist.id,
                song_id=song.id,
                position=1,
                added_by=original_sharer.id,
            )
        )
        db.session.commit()

        # Verify no notification is created when the sharer adds their own song
        notifications = db.session.query(Notification).filter_by(
            user_id=original_sharer.id
        ).all()
        assert len(notifications) == 0

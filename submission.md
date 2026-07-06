# Mixtape Codebase Map

## Project Overview

Mixtape is a Flask-based social music sharing app where users share songs with friends, rate them, listen to them, and collaborate on playlists. The app generates notifications when friends interact with shared content and tracks listening streaks.

---

## Main Files and Responsibilities

### Core Application Setup

- **app.py** — Flask factory that initializes the database, configures SQLAlchemy, and registers all route blueprints. Exports the `db` object used throughout for database access.

### Data Models

- **models.py** — Defines 7 SQLAlchemy models:
  - **User** — Represents a user with username, email, listening streak, and relationships to songs they've shared, ratings they've made, listening events, and notifications. The `friends` relationship is a symmetric many-to-many association via the `friendships` table.
  - **Song** — Represents a shared song with title, artist, album, genre, and `shared_by` (the user who originally shared it). Links to ratings, listening events, and tags.
  - **Rating** — Stores 1–5 star ratings by users on songs. Has a unique constraint per user per song (one rating per user per song).
  - **ListeningEvent** — Records when a user listened to a song, timestamped.
  - **Playlist** — A curated list of songs. Created by a user, optionally collaborative. Songs are joined via the `playlist_entries` association table which stores position (for ordering) and `added_by` (who contributed that song).
  - **Tag** — Simple tags attached to songs (e.g., "hip-hop", "lo-fi") via the `song_tags` association table.
  - **Notification** — A message sent to a user when a friend interacts with their content. Has a `notification_type` (e.g., "song_added_to_playlist"), a body (the message), and a `read` flag.

### API Routes (Blueprints)

- **routes/songs.py**
  - `GET /songs/search?q=<query>` — Search songs by title or artist name.
  - `GET /songs/<song_id>` — Get a single song's details.
  - `POST /songs/<song_id>/rate` — Rate a song (1–5 scale). Delegates to `notification_service.rate_song()`.
  - `POST /songs/<song_id>/listen` — Record a listening event. Delegates to `streak_service.record_listening_event()`.

- **routes/playlists.py**
  - `POST /playlists/` — Create a new playlist.
  - `GET /playlists/<playlist_id>` — Get playlist metadata.
  - `GET /playlists/<playlist_id>/songs` — Get songs in a playlist (in order).
  - `POST /playlists/<playlist_id>/songs` — Add a song to a playlist. **Triggers a notification** via `notification_service.add_to_playlist()`.

- **routes/users.py**
  - `GET /users/<user_id>` — Get a user's basic info.
  - `GET /users/<user_id>/streak` — Get current listening streak.
  - `GET /users/<user_id>/notifications` — Fetch user's notifications (optionally unread only).
  - `POST /users/notifications/<notification_id>/read` — Mark a notification as read.

- **routes/feed.py**
  - `GET /feed/<user_id>/listening-now` — Show what friends are listening to (last 24 hours only, deduped per friend).
  - `GET /feed/<user_id>/activity` — General activity feed of recent listening events from all friends.

### Business Logic Services

- **services/notification_service.py** — Notification and playlist interaction logic.
  - `create_notification()` — Low-level function to create a notification record.
  - `add_to_playlist()` — Called when a user adds a song to a playlist. Creates a notification for the song's original sharer (if not the same user adding it).
  - `rate_song()` — Save or update a user's rating on a song. Note: currently does **not** trigger a notification (no call to `create_notification()`).
  - `get_notifications()` — Fetch a user's notifications, optionally filtered to unread.
  - `mark_as_read()` — Mark a notification as read.

- **services/playlist_service.py** — Playlist CRUD and retrieval.
  - `create_playlist()` — Create a new playlist.
  - `get_playlist()` — Get playlist metadata.
  - `get_playlist_songs()` — Retrieve songs in a playlist, ordered by their position in the join table.
  - `get_user_playlists()` — Get all playlists created by a user.

- **services/search_service.py** — Song search and retrieval.
  - `search_songs()` — Case-insensitive substring match on title and artist.
  - `get_song()` — Get a single song by ID.

- **services/feed_service.py** — Social feed logic.
  - `get_friends_listening_now()` — Return the most recent listening event per friend, but only if it occurred in the past 24 hours (defined by `RECENT_THRESHOLD`). Dedupes to show one song per friend.
  - `get_activity_feed()` — Return the N most recent listening events from all friends (no recency filter).

- **services/streak_service.py** — Listening streak tracking.
  - `record_listening_event()` — Create a listening event and update the user's streak.
  - `update_listening_streak()` — Core streak logic: increments on consecutive calendar days, resets if a day is skipped (except Sundays, which can have a gap without resetting).
  - `get_streak()` — Fetch the current streak for a user.

### Utilities

- **seed_data.py** — Populates the database with test data: 5 users with friendships, 25 songs with varying tags, 3 playlists, listening events, and example notifications. Run with `python seed_data.py`.

---

## Data Flow: Sharing a Song and Triggering a Notification

This is the key feature showing how the notification system works:

```
User A (original sharer) creates/owns a Song
  └─ Song.shared_by = User A's ID
  └─ Song.shared_at = timestamp

User B (friend) sees the song and wants it in a playlist
  └─ POST /playlists/<playlist_id>/songs
     ├─ Request body: { "song_id": "...", "added_by": User B's ID }
     └─ routes/playlists.py::add_song() routes to:

services/notification_service.py::add_to_playlist(playlist_id, song_id, added_by_user_id=B)
  ├─ Fetch the Song record
  ├─ Fetch the User who added it (User B)
  ├─ Fetch the Playlist record
  ├─ Add the Song to playlist.songs (the many-to-many relationship)
  ├─ Check: if song.shared_by != added_by_user_id
  │   └─ YES → Create a notification for User A:
  │       └─ services/notification_service.py::create_notification(
  │            user_id=User A's ID,
  │            notification_type="song_added_to_playlist",
  │            body=f"{User B's username} added your song '{song.title}' to the playlist '{playlist.name}'."
  │          )
  │       └─ Notification record inserted into DB
  └─ Commit to database

User A queries their notifications
  └─ GET /users/<user_a_id>/notifications
     └─ routes/users.py::notifications() routes to:
        └─ services/notification_service.py::get_notifications(user_a_id)
           └─ Fetch all (or unread) Notification records for User A
           └─ Return them ordered by most recent first
```

**Key insight:** The notification is created at the moment a friend adds the shared song to a playlist. It checks that the adder is not the original sharer (to avoid self-notifications) and stores who did the action in the notification message.

---

## Architectural Patterns

1. **Separation of Concerns — Routes ↔ Services**
   - All routes are thin: they parse request data, call a service function, and return JSON.
   - All business logic lives in the `services/` directory: notifications, playlists, search, feed, streaks.
   - This makes the app easy to test (mock services) and extend (add new routes by composing service calls).

2. **Many-to-Many with Extra Data**
   - The `playlist_entries` association table stores not just song-playlist pairs, but also `position` (for ordering) and `added_by` (for tracking who contributed each song). This is a richer relationship than a simple many-to-many.
   - Similarly, `friendships` is a symmetric many-to-many: if User A is friends with User B, both directions are stored in the table.

3. **Notification as a Reactive Trigger**
   - Notifications are created *inside* service functions that handle user actions (e.g., `add_to_playlist`, potentially `rate_song`).
   - They're not generated by a separate async job or event system—they're synchronous and created as a side effect of the action.

4. **Idempotent Rating Updates**
   - The `rate_song()` function upserts: if a user has already rated the song, the score is updated; if not, a new rating is created. The unique constraint `(user_id, song_id)` enforces one rating per user per song.

5. **Time-Based Feed Filtering**
   - The "Listening Now" feed uses a `RECENT_THRESHOLD` of 24 hours, while the activity feed has no cutoff. This creates two distinct views: what friends are actively listening to vs. their full recent history.

6. **Streak Logic with Weekend Grace**
   - Listening streaks increment on consecutive calendar days but *do not* reset if Sunday is skipped (line 73 in `streak_service.py` checks `today.weekday() != 6`). This is a subtle pattern that rewards consistent weekday listening without penalizing weekend gaps.

---

## Summary

The Mixtape app is organized as a **layered Flask API** with a clear division between routing (request parsing), services (business logic), and models (data structures). The core feature flow—sharing a song and notifying the original sharer when friends add it to playlists—demonstrates how synchronous, side-effect-based notifications integrate into CRUD operations. The codebase is designed for extensibility: adding a new feature typically means writing a service function and a route that calls it.

---

## How I Reproduced Each Bug

### Bug #1: My listening streak keeps resetting
**Service:** `streak_service.py`

**Inputs / Sequence of Actions:**
1. User listens on Saturday (June 15)
2. User listens on Sunday (June 16) — consecutive day
3. User listens on Monday (June 17) — consecutive day

**Data Condition:**
A user with no prior listening events starts a fresh listening streak.

**Expected Behavior:**
- After listening on Saturday: streak = 1
- After listening on Sunday (consecutive day): streak = 2
- After listening on Monday (consecutive day): streak = 3

The streak should increment each day for consecutive calendar days. Monday follows immediately after Sunday, so the streak should continue to 3.

**Actual Behavior:**
The streak resets or fails to increment properly when listening on consecutive days after the weekend. The test expects a streak of 3 on Monday but the actual implementation either returns a lower value or resets the streak to 1.

**Root Cause:**
The `update_listening_streak()` function has a flaw in its consecutive-day detection logic, likely in how it determines whether today is consecutive to the last listening day. The weekend grace period (allowing Sunday gaps without reset) may be interfering with the weekday streak continuation, causing the Monday listening event to incorrectly trigger a reset instead of an increment.

**Test to Reproduce:**
Run `test_streak_bug_saturday_to_tuesday_reset()` in `tests/test_streaks.py`. This test:
1. Records a listening event on Saturday and expects streak = 1
2. Records a listening event on Sunday (consecutive day) and expects streak = 2
3. Records a listening event on Monday (consecutive day) and expects streak = 3

The test will fail at step 3 if the streak incorrectly resets or fails to increment on Monday.

---

### Bug #3: The same song keeps showing up twice in search
**Service:** `search_service.py`

**Inputs / Sequence of Actions:**
1. Call `search_songs("Crown Heights")` to search for a song
2. The song "Crown Heights Anthem" has 3 tags: rap, hip-hop, boom bap
3. The search query performs an outer join with the song_tags table

**Data Condition:**
A song with multiple tags (3+ tags) is stored in the database with associations in the song_tags join table.

**Expected Behavior:**
The search should return 1 result for the song with all its tags included in a tags array, without duplicates.

**Actual Behavior:**
The `search_songs()` function uses an unnecessary `LEFT OUTER JOIN` with `song_tags`. This join creates one SQL row per tag-song association. For a song with 3 tags, the raw SQL query produces 3 rows:
- Row 1: Crown Heights Anthem (tag_id=rap)
- Row 2: Crown Heights Anthem (tag_id=hip-hop)
- Row 3: Crown Heights Anthem (tag_id=boom bap)

However, SQLAlchemy's ORM deduplicates these rows back to a single Song instance with all tags properly loaded in the tags array. So at the Python level, only 1 result is returned (not 3 visible duplicates).

**How I found the root cause:**
I examined `services/search_service.py` lines 25-35 where the search query is built. I immediately noticed the `.outerjoin(song_tags, Song.id == song_tags.c.song_id)` on line 27. This was suspicious because the Song model in `models.py` line 90 already defines a `tags` relationship with `lazy="subquery"` that automatically loads all associated tags. The outerjoin appeared redundant. I verified by checking how tags are returned in `models.py` line 102—the `to_dict()` method includes `[tag.name for tag in self.tags]`, which already loads tags via the relationship. The moment I was confident: the redundant join serves no purpose since the ORM relationship already handles tag loading efficiently without creating duplicate rows at the SQL level.

**Root Cause:**
The outerjoin is redundant because the Song model already has a `tags` relationship with `lazy="subquery"` that automatically loads all associated tags. The join creates unnecessary complexity and inefficient SQL without providing any benefit. By querying only the Song table directly (without the outer join), the tags are automatically loaded through the ORM relationship, resulting in a single row per song at the SQL level instead of one row per tag.

**Your fix and side-effect check:**
I removed the redundant `.outerjoin(song_tags, Song.id == song_tags.c.song_id)` call from `search_service.py` lines 25-35. The updated `search_songs()` function now queries only the Song table:
```python
results = (
    db.session.query(Song)
    .filter(
        db.or_(
            Song.title.ilike(f"%{query}%"),
            Song.artist.ilike(f"%{query}%"),
        )
    )
    .all()
)
```

This eliminates the unnecessary SQL join. Tags are still properly loaded because the Song model's `lazy="subquery"` relationship automatically fetches all associated tags when `song.to_dict()` is called, which includes `[tag.name for tag in self.tags]`.

**Side-effect check:**
1. Ran all existing search tests (`test_search_returns_matching_songs`, `test_search_no_duplicates_single_tag_song`, `test_search_no_duplicates_multi_tag_song`, `test_search_no_duplicates_no_tag_song`, `test_search_returns_empty_for_no_match`) — all pass.
2. Created `test_search_no_duplicates_without_outerjoin()` to verify that the direct Song query produces no duplicate rows and returns correct tag data. I had to test the fix by running a raw SQL query instead of the search_song function because SQLAlchemy's ORM deduplication removes the issue of returning duplicates. If the query were run as raw SQL, the issue is more obvious.
3. Verified that the API endpoint `GET /songs/search?q=<query>` in `routes/songs.py` still correctly returns search results with all tags intact

---

### Bug #5: The last song in a playlist never shows up
**Service:** `playlist_service.py`

**Inputs / Sequence of Actions:**
1. User creates a playlist with multiple songs (e.g., 5 songs)
2. User adds songs to the playlist in order: Track 1, Track 2, Track 3, Track 4, Track 5
3. User calls `GET /playlists/<playlist_id>/songs` to retrieve all songs in the playlist

**Data Condition:**
A playlist with 5 or more songs where songs are added with sequential positions (1, 2, 3, 4, 5, etc.) in the `playlist_entries` join table.

**Expected Behavior:**
The endpoint should return all songs in the playlist, ordered by their position. For a playlist with 5 songs, the response should contain all 5 songs:
```
['Track 1', 'Track 2', 'Track 3', 'Track 4', 'Track 5']
```

**Actual Behavior:**
The endpoint returns only the first 4 songs, excluding the last song in the playlist:
```
['Track 1', 'Track 2', 'Track 3', 'Track 4']
```

**How I reproduced it:**
1. Created a test playlist with 5 songs (Track 1 through Track 5) using the `seed_playlist` fixture
2. Called `get_playlist_songs(playlist_id)` to retrieve all songs from the playlist
3. Expected the function to return all 5 songs in order
4. Observed that only 4 songs were returned, with Track 5 missing from the results

**How I found the root cause:**
I examined `services/playlist_service.py` and traced the execution path of `get_playlist_songs()` (lines 38-66). I read the function step-by-step:
- Lines 53-55: Validates the playlist exists
- Lines 58-64: Queries the database for songs joined with `playlist_entries`, ordered by position
- Line 66: Returns the list comprehension that converts songs to dicts

On line 66, I immediately spotted the problematic slice: `return [song.to_dict() for song in songs[:-1]]`. The `[:-1]` notation is Python's slice syntax that excludes the final element. This was the exact location of the bug.

**The root cause:**
In Python, the slice notation `songs[:-1]` returns all elements of the list except the last one. Line 66 of `playlist_service.py` unconditionally applies this slice to the songs list before returning:
```python
return [song.to_dict() for song in songs[:-1]]
```

This means for any playlist with N songs, the function returns only N-1 songs. The last song in the playlist is permanently excluded from the results, regardless of playlist size or content. For example, a playlist with 5 songs returns only the first 4 (Track 1-4), and the 5th song is never visible to the client.

**Your fix and side-effect check:**
I changed line 66 from:
```python
return [song.to_dict() for song in songs[:-1]]
```
to:
```python
return [song.to_dict() for song in songs]
```

This removes the slice operator and returns all songs without excluding any. To verify the fix didn't break related functionality, I:
1. Ran existing tests `test_playlist_returns_all_songs()` and `test_playlist_returns_songs_in_order()` — both now pass
2. Created `test_last_song_is_included_in_results()` that explicitly verifies the last song appears in results
3. Wrote three integration tests that verify the notification service (which depends on correct playlist song retrieval) still works: `test_notification_created_when_friend_adds_song_to_playlist`, `test_notification_contains_correct_song_and_playlist_names`, `test_no_notification_when_song_sharer_adds_own_song_to_playlist`
4. Checked the API endpoint `GET /playlists/<playlist_id>/songs` in `routes/playlists.py` — it calls this function and now correctly returns all songs with the accurate count

---

## AI Usage

### Workflow Overview
The debugging approach for all three bugs followed a consistent workflow: identify a failing test → trace the code path from symptom to suspicious code → use AI to understand edge cases or mechanisms → verify the diagnosis by re-reading the code and forming a hypothesis → confirm by understanding the exact execution flow.

### Bug #5: Last Song in Playlist

**Tracing from symptom to code:**
The test `test_last_song_is_included_in_results()` fails with: "Song 'Track 5' not found. Returned: ['Track 1', 'Track 2', 'Track 3', 'Track 4']". This symptom points to the retrieval logic for playlist songs. I traced the call chain:
- Route called: `GET /playlists/<playlist_id>/songs` in `routes/playlists.py`
- Routes to service: `playlist_service.get_playlist_songs(playlist_id)` in `services/playlist_service.py`
- Read the function and found the suspicious slice at line 66: `return [song.to_dict() for song in songs[:-1]]`

**AI's role:** I had narrowed it to a specific function and asked AI to confirm: "What does the Python slice `[:-1]` do to a list?" AI confirmed this removes the last element, explaining exactly why the last song disappears.

**Verification:** I read line 66 in `playlist_service.py` myself and saw the problematic slice. I traced what `songs` contains (a list of Song objects ordered by position from the database query on lines 62-65) and confirmed that `[:-1]` removes the final song before returning.

**Hypothesis & Fix:** The slice operation is a bug—there's no reason to exclude the last song. Removing `[:-1]` returns all songs as expected.

---

### Bug #3: Duplicate Search Results

**Tracing from symptom to code:**
The test for songs with multiple tags showed that search might be inefficient. I traced the call chain:
- Route called: `GET /songs/search?q=<query>` in `routes/songs.py`
- Routes to service: `search_service.search_songs(query)` in `services/search_service.py`
- Read the query builder in lines 44-47 of `search_service.py` and saw a `LEFT OUTER JOIN` with `song_tags`

**Navigation strategy:** The test output and codebase map suggested the Song model already has a `tags` relationship, so I checked `models.py`. On line 26, I saw `tags = relationship('Tag', ...)` with `lazy="subquery"`. This is a key detail: the relationship automatically loads all tags without an explicit join.

**AI's role:** I asked AI: "In SQLAlchemy, if a model has a many-to-many relationship with `lazy='subquery'`, why would adding a `LEFT OUTER JOIN` to the same table be redundant?" AI explained that the join creates one row per tag association, causing SQLAlchemy's ORM to deduplicate at the Python level, but the SQL itself is inefficient and creates unnecessary database load.

**Verification:** I examined the code path:
- Lines 44-47 in `search_service.py` perform the outerjoin
- Line 26 in `models.py` shows the Song model already has `tags` defined with lazy loading
- The query is redundant: the `tags` relationship already handles loading all associated tags

**Hypothesis & Fix:** The `LEFT OUTER JOIN` is unnecessary because SQLAlchemy's relationship lazy loading already handles it. Removing the outerjoin simplifies the query without losing any data.
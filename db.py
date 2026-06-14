"""
Single database layer. All teams, groups, matches, users, predictions live here.
"""
import sqlite3
import os
import secrets
import bcrypt
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(__file__), "wc2026.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ─────────────────────────────────────────────────────────────────────────────
# Schema
# ─────────────────────────────────────────────────────────────────────────────
def init_schema():
    with get_conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS confederations (
            id   INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        );

        CREATE TABLE IF NOT EXISTS groups (
            id     INTEGER PRIMARY KEY AUTOINCREMENT,
            name   TEXT UNIQUE NOT NULL   -- 'A'..'L'
        );

        CREATE TABLE IF NOT EXISTS teams (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            name           TEXT UNIQUE NOT NULL,
            flag           TEXT NOT NULL DEFAULT '',
            group_id       INTEGER REFERENCES groups(id),
            confederation  TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS venues (
            id   INTEGER PRIMARY KEY AUTOINCREMENT,
            key  TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS matches (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id     INTEGER REFERENCES groups(id),
            home_id      INTEGER REFERENCES teams(id),
            away_id      INTEGER REFERENCES teams(id),
            kickoff_utc  TEXT NOT NULL,   -- 'YYYY-MM-DDTHH:MM'
            venue_id     INTEGER REFERENCES venues(id),
            score_home   INTEGER,         -- NULL = not played yet
            score_away   INTEGER
        );

        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT UNIQUE NOT NULL,
            email         TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role          TEXT NOT NULL DEFAULT 'user',  -- 'admin' | 'user'
            verified      INTEGER NOT NULL DEFAULT 0,    -- 0=pending, 1=approved
            favorite_team TEXT DEFAULT '',
            tz_name       TEXT DEFAULT 'Jordan (UTC+3)',
            tz_offset     INTEGER DEFAULT 3,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS sessions (
            token      TEXT PRIMARY KEY,
            user_id    INTEGER NOT NULL REFERENCES users(id),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS predictions (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL REFERENCES users(id),
            match_id   INTEGER NOT NULL REFERENCES matches(id),
            pred_home  INTEGER NOT NULL,
            pred_away  INTEGER NOT NULL,
            submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, match_id)
        );
        """)
    # Migrate existing DBs that predate these columns/tables
    with get_conn() as c:
        for col, dflt in [("tz_name", "'Jordan (UTC+3)'"), ("tz_offset", "3")]:
            try:
                c.execute(f"ALTER TABLE users ADD COLUMN {col} TEXT DEFAULT {dflt}")
            except Exception:
                pass
        # Add verified column — if this succeeds the column is new,
        # so ALL existing accounts should be auto-approved (pre-verification era)
        try:
            c.execute("ALTER TABLE users ADD COLUMN verified INTEGER NOT NULL DEFAULT 0")
            c.execute("UPDATE users SET verified=1")  # one-time: approve everyone already in DB
        except Exception:
            pass  # column already existed — do not touch verified status
        c.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                token      TEXT PRIMARY KEY,
                user_id    INTEGER NOT NULL REFERENCES users(id),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        c.commit()


# ─────────────────────────────────────────────────────────────────────────────
# Seed lookup data
# ─────────────────────────────────────────────────────────────────────────────
_VENUES = [
    ("Azteca",    "Estadio Azteca, Mexico City"),
    ("Akron",     "Estadio Akron, Zapopan"),
    ("BBVA",      "Estadio BBVA, Guadalupe"),
    ("Jalisco",   "Estadio Jalisco, Guadalajara"),
    ("BMO",       "BMO Field, Toronto"),
    ("BC",        "BC Place, Vancouver"),
    ("Lumen",     "Lumen Field, Seattle"),
    ("MetLife",   "MetLife Stadium, East Rutherford NJ"),
    ("Gillette",  "Gillette Stadium, Foxborough MA"),
    ("HardRock",  "Hard Rock Stadium, Miami Gardens FL"),
    ("Lincoln",   "Lincoln Financial Field, Philadelphia"),
    ("ATT",       "AT&T Stadium, Arlington TX"),
    ("SoFi",      "SoFi Stadium, Inglewood CA"),
    ("Levis",     "Levi's Stadium, Santa Clara CA"),
    ("NRG",       "NRG Stadium, Houston TX"),
    ("Arrowhead", "Arrowhead Stadium, Kansas City MO"),
    ("Mercedes",  "Mercedes-Benz Stadium, Atlanta GA"),
]

# (name, flag, group, confederation)
_TEAMS = [
    ("Mexico",                 "🇲🇽", "A", "CONCACAF"),
    ("South Africa",           "🇿🇦", "A", "CAF"),
    ("Korea Republic",         "🇰🇷", "A", "AFC"),
    ("Czechia",                "🇨🇿", "A", "UEFA"),
    ("Canada",                 "🇨🇦", "B", "CONCACAF"),
    ("Bosnia and Herzegovina", "🇧🇦", "B", "UEFA"),
    ("Qatar",                  "🇶🇦", "B", "AFC"),
    ("Switzerland",            "🇨🇭", "B", "UEFA"),
    ("Brazil",                 "🇧🇷", "C", "CONMEBOL"),
    ("Morocco",                "🇲🇦", "C", "CAF"),
    ("Haiti",                  "🇭🇹", "C", "CONCACAF"),
    ("Scotland",               "🏴󠁧󠁢󠁳󠁣󠁴󠁿", "C", "UEFA"),
    ("USA",                    "🇺🇸", "D", "CONCACAF"),
    ("Paraguay",               "🇵🇾", "D", "CONMEBOL"),
    ("Australia",              "🇦🇺", "D", "AFC"),
    ("Turkey",                 "🇹🇷", "D", "UEFA"),
    ("Germany",                "🇩🇪", "E", "UEFA"),
    ("Curaçao",                "🇨🇼", "E", "CONCACAF"),
    ("Ivory Coast",            "🇨🇮", "E", "CAF"),
    ("Ecuador",                "🇪🇨", "E", "CONMEBOL"),
    ("Netherlands",            "🇳🇱", "F", "UEFA"),
    ("Japan",                  "🇯🇵", "F", "AFC"),
    ("Sweden",                 "🇸🇪", "F", "UEFA"),
    ("Tunisia",                "🇹🇳", "F", "CAF"),
    ("Belgium",                "🇧🇪", "G", "UEFA"),
    ("Egypt",                  "🇪🇬", "G", "CAF"),
    ("Iran",                   "🇮🇷", "G", "AFC"),
    ("New Zealand",            "🇳🇿", "G", "OFC"),
    ("Spain",                  "🇪🇸", "H", "UEFA"),
    ("Uruguay",                "🇺🇾", "H", "CONMEBOL"),
    ("Saudi Arabia",           "🇸🇦", "H", "AFC"),
    ("Cape Verde",             "🇨🇻", "H", "CAF"),
    ("France",                 "🇫🇷", "I", "UEFA"),
    ("Senegal",                "🇸🇳", "I", "CAF"),
    ("Iraq",                   "🇮🇶", "I", "AFC"),
    ("Norway",                 "🇳🇴", "I", "UEFA"),
    ("Argentina",              "🇦🇷", "J", "CONMEBOL"),
    ("Algeria",                "🇩🇿", "J", "CAF"),
    ("Austria",                "🇦🇹", "J", "UEFA"),
    ("Jordan",                 "🇯🇴", "J", "AFC"),
    ("Portugal",               "🇵🇹", "K", "UEFA"),
    ("DR Congo",               "🇨🇩", "K", "CAF"),
    ("Uzbekistan",             "🇺🇿", "K", "AFC"),
    ("Colombia",               "🇨🇴", "K", "CONMEBOL"),
    ("England",                "🏴󠁧󠁢󠁥󠁮󠁧󠁿", "L", "UEFA"),
    ("Croatia",                "🇭🇷", "L", "UEFA"),
    ("Ghana",                  "🇬🇭", "L", "CAF"),
    ("Panama",                 "🇵🇦", "L", "CONCACAF"),
]

# (home, away, kickoff_utc, venue_key, score_home, score_away)
_MATCHES = [
    ("Mexico",          "South Africa",           "2026-06-11T19:00", "Azteca",    2,    0),
    ("Korea Republic",  "Czechia",                "2026-06-12T02:00", "Akron",     2,    1),
    ("Czechia",         "South Africa",           "2026-06-18T16:00", "Mercedes",  None, None),
    ("Mexico",          "Korea Republic",         "2026-06-19T01:00", "Akron",     None, None),
    ("Czechia",         "Mexico",                 "2026-06-25T01:00", "Azteca",    None, None),
    ("South Africa",    "Korea Republic",         "2026-06-25T01:00", "BBVA",      None, None),
    ("Canada",          "Bosnia and Herzegovina", "2026-06-12T19:00", "BMO",       1,    1),
    ("Qatar",           "Switzerland",            "2026-06-13T19:00", "Levis",     None, None),
    ("Switzerland",     "Bosnia and Herzegovina", "2026-06-18T19:00", "SoFi",      None, None),
    ("Canada",          "Qatar",                  "2026-06-18T22:00", "BC",        None, None),
    ("Switzerland",     "Canada",                 "2026-06-24T19:00", "BC",        None, None),
    ("Bosnia and Herzegovina", "Qatar",           "2026-06-24T19:00", "Lumen",     None, None),
    ("Brazil",          "Morocco",                "2026-06-13T22:00", "MetLife",   None, None),
    ("Haiti",           "Scotland",               "2026-06-14T01:00", "Gillette",  None, None),
    ("Scotland",        "Morocco",                "2026-06-19T22:00", "Gillette",  None, None),
    ("Brazil",          "Haiti",                  "2026-06-20T00:30", "Lincoln",   None, None),
    ("Scotland",        "Brazil",                 "2026-06-24T22:00", "HardRock",  None, None),
    ("Morocco",         "Haiti",                  "2026-06-24T22:00", "Mercedes",  None, None),
    ("USA",             "Paraguay",               "2026-06-13T01:00", "SoFi",      4,    1),
    ("Australia",       "Turkey",                 "2026-06-14T04:00", "BC",        None, None),
    ("USA",             "Australia",              "2026-06-19T19:00", "Lumen",     None, None),
    ("Turkey",          "Paraguay",               "2026-06-20T03:00", "Levis",     None, None),
    ("Turkey",          "USA",                    "2026-06-26T02:00", "SoFi",      None, None),
    ("Paraguay",        "Australia",              "2026-06-26T02:00", "Levis",     None, None),
    ("Germany",         "Curaçao",                "2026-06-14T17:00", "NRG",       None, None),
    ("Ivory Coast",     "Ecuador",                "2026-06-14T23:00", "Lincoln",   None, None),
    ("Germany",         "Ivory Coast",            "2026-06-20T20:00", "BMO",       None, None),
    ("Ecuador",         "Curaçao",                "2026-06-21T00:00", "Arrowhead", None, None),
    ("Curaçao",         "Ivory Coast",            "2026-06-25T20:00", "Lincoln",   None, None),
    ("Ecuador",         "Germany",                "2026-06-25T20:00", "MetLife",   None, None),
    ("Netherlands",     "Japan",                  "2026-06-14T20:00", "ATT",       None, None),
    ("Sweden",          "Tunisia",                "2026-06-15T02:00", "BBVA",      None, None),
    ("Netherlands",     "Sweden",                 "2026-06-20T17:00", "NRG",       None, None),
    ("Tunisia",         "Japan",                  "2026-06-21T04:00", "BBVA",      None, None),
    ("Japan",           "Sweden",                 "2026-06-25T22:00", "ATT",       None, None),
    ("Tunisia",         "Netherlands",            "2026-06-25T23:00", "Arrowhead", None, None),
    ("Iran",            "New Zealand",            "2026-06-16T01:00", "SoFi",      None, None),
    ("Belgium",         "Egypt",                  "2026-06-16T02:00", "Lumen",     None, None),
    ("New Zealand",     "Egypt",                  "2026-06-22T01:00", "BC",        None, None),
    ("Belgium",         "Iran",                   "2026-06-22T02:00", "SoFi",      None, None),
    ("Egypt",           "Iran",                   "2026-06-27T03:00", "Lumen",     None, None),
    ("New Zealand",     "Belgium",                "2026-06-27T03:00", "BC",        None, None),
    ("Spain",           "Cape Verde",             "2026-06-15T16:00", "Mercedes",  None, None),
    ("Saudi Arabia",    "Uruguay",                "2026-06-15T22:00", "HardRock",  None, None),
    ("Spain",           "Saudi Arabia",           "2026-06-21T16:00", "Mercedes",  None, None),
    ("Uruguay",         "Cape Verde",             "2026-06-21T22:00", "HardRock",  None, None),
    ("Cape Verde",      "Saudi Arabia",           "2026-06-27T00:00", "NRG",       None, None),
    ("Uruguay",         "Spain",                  "2026-06-27T00:00", "Akron",     None, None),
    ("France",          "Senegal",                "2026-06-16T19:00", "MetLife",   None, None),
    ("Iraq",            "Norway",                 "2026-06-16T22:00", "Gillette",  None, None),
    ("France",          "Iraq",                   "2026-06-22T21:00", "Lincoln",   None, None),
    ("Norway",          "Senegal",                "2026-06-23T00:00", "MetLife",   None, None),
    ("Norway",          "France",                 "2026-06-26T19:00", "Gillette",  None, None),
    ("Senegal",         "Iraq",                   "2026-06-26T19:00", "BMO",       None, None),
    ("Argentina",       "Algeria",                "2026-06-17T01:00", "Arrowhead", None, None),
    ("Austria",         "Jordan",                 "2026-06-17T04:00", "Levis",     None, None),
    ("Argentina",       "Austria",                "2026-06-23T01:00", "ATT",       None, None),
    ("Jordan",          "Algeria",                "2026-06-23T04:00", "Levis",     None, None),
    ("Algeria",         "Austria",                "2026-06-28T01:00", "Arrowhead", None, None),
    ("Jordan",          "Argentina",              "2026-06-28T01:00", "ATT",       None, None),
    ("Portugal",        "DR Congo",               "2026-06-17T17:00", "NRG",       None, None),
    ("Uzbekistan",      "Colombia",               "2026-06-18T02:00", "Azteca",    None, None),
    ("Portugal",        "Uzbekistan",             "2026-06-23T17:00", "NRG",       None, None),
    ("Colombia",        "DR Congo",               "2026-06-24T02:00", "Akron",     None, None),
    ("Colombia",        "Portugal",               "2026-06-27T23:30", "HardRock",  None, None),
    ("DR Congo",        "Uzbekistan",             "2026-06-27T23:30", "Mercedes",  None, None),
    ("England",         "Croatia",                "2026-06-17T20:00", "ATT",       None, None),
    ("Ghana",           "Panama",                 "2026-06-17T23:00", "BMO",       None, None),
    ("England",         "Ghana",                  "2026-06-23T20:00", "Gillette",  None, None),
    ("Panama",          "Croatia",                "2026-06-23T23:00", "BMO",       None, None),
    ("Panama",          "England",                "2026-06-27T21:00", "MetLife",   None, None),
    ("Croatia",         "Ghana",                  "2026-06-27T21:00", "Lincoln",   None, None),
]

_SEED_USERS = [
    ("Mohammad Alhassan", "m.alhasan@minerets.com", "Minerets@2026", "user"),
    ("Mohammad Souqi",    "m.souqi@minerets.com",   "Minerets@2026", "user"),
]


def seed_data():
    with get_conn() as c:
        # groups
        for g in "ABCDEFGHIJKL":
            c.execute("INSERT OR IGNORE INTO groups(name) VALUES(?)", (g,))

        # venues
        for key, name in _VENUES:
            c.execute("INSERT OR IGNORE INTO venues(key,name) VALUES(?,?)", (key, name))

        # teams
        for name, flag, grp, conf in _TEAMS:
            grp_id = c.execute("SELECT id FROM groups WHERE name=?", (grp,)).fetchone()["id"]
            c.execute(
                "INSERT OR IGNORE INTO teams(name,flag,group_id,confederation) VALUES(?,?,?,?)",
                (name, flag, grp_id, conf),
            )

        # matches (only insert if table is empty)
        if c.execute("SELECT COUNT(*) FROM matches").fetchone()[0] == 0:
            for home, away, kickoff, venue_key, sh, sa in _MATCHES:
                home_id  = c.execute("SELECT id FROM teams WHERE name=?", (home,)).fetchone()["id"]
                away_id  = c.execute("SELECT id FROM teams WHERE name=?", (away,)).fetchone()["id"]
                venue_id = c.execute("SELECT id FROM venues WHERE key=?", (venue_key,)).fetchone()["id"]
                grp_id   = c.execute("SELECT group_id FROM teams WHERE id=?", (home_id,)).fetchone()["group_id"]
                c.execute(
                    "INSERT INTO matches(group_id,home_id,away_id,kickoff_utc,venue_id,score_home,score_away) VALUES(?,?,?,?,?,?,?)",
                    (grp_id, home_id, away_id, kickoff, venue_id, sh, sa),
                )

        # seed users — always verified
        for username, email, password, role in _SEED_USERS:
            if not c.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
                pw = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
                c.execute(
                    "INSERT INTO users(username,email,password_hash,role,verified) VALUES(?,?,?,?,1)",
                    (username, email, pw, role),
                )
            else:
                # Ensure existing seed accounts stay verified
                c.execute("UPDATE users SET verified=1 WHERE email=?", (email,))


# ─────────────────────────────────────────────────────────────────────────────
# Query helpers
# ─────────────────────────────────────────────────────────────────────────────
def _now_utc():
    return datetime.now(timezone.utc)

def _parse(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc)

def _status(kickoff_utc, score_home, score_away):
    if score_home is not None and score_away is not None:
        return "completed"
    if _now_utc() >= _parse(kickoff_utc):
        return "live"
    return "upcoming"

def _is_locked(kickoff_utc):
    return _now_utc() >= _parse(kickoff_utc)


def get_matches():
    with get_conn() as c:
        rows = c.execute("""
            SELECT m.id, g.name AS grp,
                   ht.name AS home, ht.flag AS home_flag,
                   at.name AS away, at.flag AS away_flag,
                   m.kickoff_utc, v.name AS venue,
                   m.score_home, m.score_away
            FROM matches m
            JOIN groups g  ON g.id  = m.group_id
            JOIN teams  ht ON ht.id = m.home_id
            JOIN teams  at ON at.id = m.away_id
            JOIN venues v  ON v.id  = m.venue_id
            ORDER BY m.kickoff_utc, m.id
        """).fetchall()
    out = []
    for r in rows:
        out.append({
            "id":          r["id"],
            "group":       r["grp"],
            "home":        r["home"],
            "home_flag":   r["home_flag"],
            "away":        r["away"],
            "away_flag":   r["away_flag"],
            "kickoff_utc": r["kickoff_utc"],
            "venue":       r["venue"],
            "score_home":  r["score_home"],
            "score_away":  r["score_away"],
            "status":      _status(r["kickoff_utc"], r["score_home"], r["score_away"]),
            "locked":      _is_locked(r["kickoff_utc"]),
        })
    return out


def get_teams():
    with get_conn() as c:
        rows = c.execute("""
            SELECT t.id, t.name, t.flag, g.name AS grp, t.confederation
            FROM teams t JOIN groups g ON g.id=t.group_id
            ORDER BY g.name, t.name
        """).fetchall()
    return [dict(r) for r in rows]


def get_groups():
    with get_conn() as c:
        rows = c.execute("SELECT name FROM groups ORDER BY name").fetchall()
    return [r["name"] for r in rows]


def get_standings():
    teams  = get_teams()
    matches = get_matches()
    s = {}
    for t in teams:
        s[t["name"]] = {"group": t["grp"], "flag": t["flag"],
                        "P":0,"W":0,"D":0,"L":0,"GF":0,"GA":0,"GD":0,"Pts":0}
    for m in matches:
        if m["status"] != "completed":
            continue
        h, a, sh, sa = m["home"], m["away"], m["score_home"], m["score_away"]
        for t in (h, a):
            if t not in s:
                s[t] = {"group":"?","flag":"🏳","P":0,"W":0,"D":0,"L":0,"GF":0,"GA":0,"GD":0,"Pts":0}
        s[h]["P"]+=1; s[a]["P"]+=1
        s[h]["GF"]+=sh; s[h]["GA"]+=sa
        s[a]["GF"]+=sa; s[a]["GA"]+=sh
        if sh>sa:   s[h]["W"]+=1; s[h]["Pts"]+=3; s[a]["L"]+=1
        elif sa>sh: s[a]["W"]+=1; s[a]["Pts"]+=3; s[h]["L"]+=1
        else:       s[h]["D"]+=1; s[h]["Pts"]+=1; s[a]["D"]+=1; s[a]["Pts"]+=1
    for t in s:
        s[t]["GD"] = s[t]["GF"] - s[t]["GA"]
    return s


# ─────────────────────────────────────────────────────────────────────────────
# Scoring
# ─────────────────────────────────────────────────────────────────────────────
def calc_points(ph, pa, ah, aa):
    """
    3 pts: exact score match (including exact draw e.g. 1-1 predicted == 1-1 actual)
    1 pt : correct outcome (home win / away win / draw) but wrong score
    0 pts: wrong outcome
    """
    def outcome(h, a): return "H" if h > a else ("A" if a > h else "D")
    if ph == ah and pa == aa:
        return 3
    if outcome(ph, pa) == outcome(ah, aa):
        return 1
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# Predictions
# ─────────────────────────────────────────────────────────────────────────────
def save_prediction(user_id, match_id, pred_home, pred_away):
    with get_conn() as c:
        c.execute("""
            INSERT INTO predictions(user_id,match_id,pred_home,pred_away)
            VALUES(?,?,?,?)
            ON CONFLICT(user_id,match_id) DO UPDATE SET
              pred_home=excluded.pred_home,
              pred_away=excluded.pred_away,
              submitted_at=CURRENT_TIMESTAMP
        """, (user_id, match_id, pred_home, pred_away))


def get_user_predictions(user_id):
    with get_conn() as c:
        rows = c.execute(
            "SELECT match_id,pred_home,pred_away FROM predictions WHERE user_id=?",
            (user_id,),
        ).fetchall()
    return {r["match_id"]: (r["pred_home"], r["pred_away"]) for r in rows}


def get_all_predictions_for_match(match_id):
    with get_conn() as c:
        rows = c.execute("""
            SELECT u.username, p.pred_home, p.pred_away, p.submitted_at
            FROM predictions p JOIN users u ON u.id=p.user_id
            WHERE p.match_id=?
            ORDER BY u.username
        """, (match_id,)).fetchall()
    return [dict(r) for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
# Admin: update match result
# ─────────────────────────────────────────────────────────────────────────────
def set_match_result(match_id, score_home, score_away):
    with get_conn() as c:
        c.execute(
            "UPDATE matches SET score_home=?, score_away=? WHERE id=?",
            (score_home, score_away, match_id),
        )


def clear_match_result(match_id):
    with get_conn() as c:
        c.execute(
            "UPDATE matches SET score_home=NULL, score_away=NULL WHERE id=?",
            (match_id,),
        )


# ─────────────────────────────────────────────────────────────────────────────
# Leaderboard
# ─────────────────────────────────────────────────────────────────────────────
def get_leaderboard():
    matches   = get_matches()
    completed = {m["id"]: m for m in matches if m["status"] == "completed"}

    with get_conn() as c:
        users    = c.execute("SELECT id, username, favorite_team FROM users ORDER BY username").fetchall()
        all_pred = c.execute("SELECT user_id,match_id,pred_home,pred_away FROM predictions").fetchall()

    upreds = {}
    for p in all_pred:
        upreds.setdefault(p["user_id"], []).append(p)

    rows = []
    for u in users:
        preds = upreds.get(u["id"], [])
        pts = exact = winner = wrong = no_pred_on_done = 0
        for p in preds:
            m = completed.get(p["match_id"])
            if m:
                pt = calc_points(p["pred_home"], p["pred_away"], m["score_home"], m["score_away"])
                pts += pt
                if pt == 3: exact  += 1
                elif pt==1: winner += 1
                else:       wrong  += 1
        no_pred_on_done = len(completed) - sum(
            1 for p in preds if p["match_id"] in completed
        )
        rows.append({
            "username":    u["username"],
            "fav_team":    u["favorite_team"] or "",
            "points":      pts,
            "exact":       exact,
            "winner":      winner,
            "wrong":       wrong,
            "no_pred":     no_pred_on_done,
            "total_pred":  len(preds),
        })
    rows.sort(key=lambda x: (-x["points"], -x["exact"], -x["winner"]))
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# User auth
# ─────────────────────────────────────────────────────────────────────────────
def register_user(username, email, password):
    if len(username) < 3:
        return False, "Username must be at least 3 characters."
    if len(password) < 6:
        return False, "Password must be at least 6 characters."
    pw = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    try:
        with get_conn() as c:
            # verified=0 → pending admin approval
            c.execute(
                "INSERT INTO users(username,email,password_hash,role,verified) VALUES(?,?,?,'user',0)",
                (username.strip(), email.strip().lower(), pw),
            )
        return True, "Account created! Please wait for admin verification before you can access the app."
    except Exception as e:
        if "username" in str(e): return False, "Username already taken."
        if "email"    in str(e): return False, "Email already registered."
        return False, "Registration failed."


def login_user(identifier, password):
    """Returns (status, user_dict).
    status: 'ok' | 'bad_credentials' | 'pending'
    """
    with get_conn() as c:
        row = c.execute(
            "SELECT * FROM users WHERE username=? OR email=?",
            (identifier.strip(), identifier.strip().lower()),
        ).fetchone()
    if not row:
        return "bad_credentials", None
    if not bcrypt.checkpw(password.encode(), row["password_hash"].encode()):
        return "bad_credentials", None
    verified = row["verified"]
    if str(verified) not in ("1", "True", "true"):
        return "pending", dict(row)
    return "ok", dict(row)


def update_user_field(user_id, field, value):
    allowed = {"favorite_team", "tz_name", "tz_offset"}
    if field not in allowed:
        return
    with get_conn() as c:
        c.execute(f"UPDATE users SET {field}=? WHERE id=?", (value, user_id))


def get_all_users():
    with get_conn() as c:
        rows = c.execute(
            "SELECT id,username,email,role,verified,favorite_team,created_at FROM users ORDER BY username"
        ).fetchall()
    return [dict(r) for r in rows]


def set_user_role(user_id, role):
    with get_conn() as c:
        c.execute("UPDATE users SET role=? WHERE id=?", (role, user_id))


def set_user_verified(user_id, verified: bool):
    with get_conn() as c:
        c.execute("UPDATE users SET verified=? WHERE id=?", (1 if verified else 0, user_id))


def get_pending_users():
    with get_conn() as c:
        rows = c.execute(
            "SELECT id,username,email,created_at FROM users WHERE verified=0 ORDER BY created_at"
        ).fetchall()
    return [dict(r) for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
# Sessions (persist login across page refreshes via browser cookie)
# ─────────────────────────────────────────────────────────────────────────────
def create_session(user_id: int) -> str:
    token = secrets.token_hex(32)
    with get_conn() as c:
        c.execute("INSERT INTO sessions(token,user_id) VALUES(?,?)", (token, user_id))
    return token


def get_session_user(token: str) -> dict | None:
    if not token:
        return None
    with get_conn() as c:
        row = c.execute("""
            SELECT u.* FROM sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token = ?
        """, (token,)).fetchone()
    if not row:
        return None
    # Re-check user is still verified and active
    if str(row["verified"]) not in ("1", "True", "true"):
        return None
    return dict(row)


def delete_session(token: str):
    if token:
        with get_conn() as c:
            c.execute("DELETE FROM sessions WHERE token=?", (token,))

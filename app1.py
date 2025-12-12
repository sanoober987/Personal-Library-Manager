import streamlit as st
import sqlite3
import os
import hashlib
from io import BytesIO
from PIL import Image
from datetime import datetime
import json

# ------------------- Config -------------------
st.set_page_config(page_title="📚 Personal Library Manager", page_icon="📘", layout="wide")
DB_FILE = "library.db"
COVERS_DIR = "covers"
os.makedirs(COVERS_DIR, exist_ok=True)

# ------------------- CSS -------------------
st.markdown(
    """
    <style>
    .card {
        border-radius: 12px;
        padding: 16px;
        margin-bottom: 16px;
        transition: transform .18s ease, box-shadow .18s ease;
        background: linear-gradient(180deg, rgba(255,255,255,0.92), rgba(250,250,250,0.88));
        box-shadow: 0 8px 20px rgba(15,23,42,0.06);
    }
    .card:hover {
        transform: translateY(-6px);
        box-shadow: 0 18px 40px rgba(15,23,42,0.10);
    }
    .cover-thumb {
        border-radius: 8px;
        object-fit: cover;
    }
    .meta { color: #6b7280; font-size:13px; }
    @media (max-width: 600px) {
        .cover-thumb { max-width: 110px; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ------------------- DB helpers & migration -------------------
def get_conn():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db_and_migrate():
    """
    Create table if not exists, and ensure expected columns exist.
    If an old table lacks new columns (like 'cover' or 'added_at'), ALTER TABLE to add them.
    """
    conn = get_conn()
    cur = conn.cursor()

    # Create table if not exists (minimal schema)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS books (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            author TEXT,
            genre TEXT,
            year INTEGER,
            read INTEGER DEFAULT 0
        );
        """
    )
    conn.commit()

    # Desired columns and their SQL definitions if missing
    desired_columns = {
        "cover": "TEXT",
        "added_at": "TEXT"
    }

    # Get existing columns
    cur.execute("PRAGMA table_info(books);")
    cols = [row["name"] for row in cur.fetchall()]

    # Add missing columns
    for col, definition in desired_columns.items():
        if col not in cols:
            try:
                cur.execute(f"ALTER TABLE books ADD COLUMN {col} {definition};")
                conn.commit()
            except Exception:
                print(f"Could not add column {col} (may already exist):", flush=True)

    conn.close()

# Initialize DB and migrate if needed
init_db_and_migrate()

# ------------------- Image helpers -------------------
def save_cover(uploaded_file):
    """
    Save uploaded_file to covers/ using sha256 hash of the file bytes as filename.
    Returns relative path to saved file or None on failure / no file.
    """
    if uploaded_file is None:
        return None
    try:
        data = uploaded_file.read()  # bytes
        if not data:
            return None
        # deterministic filename based on content
        h = hashlib.sha256(data).hexdigest()
        _, ext = os.path.splitext(uploaded_file.name)
        ext = ext.lower() if ext else ".png"
        filename = f"{h}{ext}"
        path = os.path.join(COVERS_DIR, filename)
        # If file not already saved, validate & save via PIL
        if not os.path.exists(path):
            img = Image.open(BytesIO(data))
            
            max_w, max_h = 1200, 1600
            if img.width > max_w or img.height > max_h:
                img.thumbnail((max_w, max_h))
            img.save(path)
        return path
    except Exception as e:
        print("Error saving cover:", e, flush=True)
        return None

# ------------------- CRUD operations -------------------
def add_book(title, author, genre, year, read_flag, cover_path):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO books (title, author, genre, year, read, cover, added_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (title.strip(), author.strip(), genre.strip() if genre else None, int(year) if year else None, 1 if read_flag else 0, cover_path, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()

def delete_book(book_id):
    # remove row and delete cover file (if exists)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT cover FROM books WHERE id = ?", (book_id,))
    row = cur.fetchone()
    if row and row["cover"]:
        try:
            if os.path.exists(row["cover"]):
                os.remove(row["cover"])
        except Exception:
            pass
    cur.execute("DELETE FROM books WHERE id = ?", (book_id,))
    conn.commit()
    conn.close()

def toggle_read(book_id, new_state):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE books SET read = ? WHERE id = ?", (1 if new_state else 0, book_id))
    conn.commit()
    conn.close()

def query_books(search_text="", genre_filter=None, year_min=None, year_max=None, read_filter=None):
    conn = get_conn()
    cur = conn.cursor()
    sql = "SELECT * FROM books WHERE 1=1"
    params = []
    if search_text:
        sql += " AND (LOWER(title) LIKE ? OR LOWER(author) LIKE ?)"
        q = f"%{search_text.lower()}%"
        params += [q, q]
    if genre_filter and genre_filter != "All":
        sql += " AND LOWER(genre) = ?"
        params.append(genre_filter.lower())
    if year_min is not None:
        sql += " AND (year IS NOT NULL AND year >= ?)"
        params.append(year_min)
    if year_max is not None:
        sql += " AND (year IS NOT NULL AND year <= ?)"
        params.append(year_max)
    if read_filter is not None:
        sql += " AND read = ?"
        params.append(1 if read_filter else 0)
    sql += " ORDER BY added_at DESC"
    cur.execute(sql, params)
    rows = cur.fetchall()
    conn.close()
    return rows

def get_genres():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT genre FROM books WHERE genre IS NOT NULL AND genre <> ''")
    rows = cur.fetchall()
    conn.close()
    return sorted({r["genre"].strip().title() for r in rows if r["genre"]})

# ------------------- Sidebar: Add Book ------------------- 

st.sidebar.header("➕ Add a new book")

with st.sidebar.form("add_book_form", clear_on_submit=True):
    form_title = st.text_input("📖 Title")
    form_author = st.text_input("✍️ Author")
    form_genre = st.text_input("🎨 Genre (e.g., Fiction, Sci-Fi)")
    form_year = st.number_input("📅 Year Published", min_value=0, max_value=2100, value=datetime.utcnow().year, step=1)
    form_cover = st.file_uploader("🖼️ Cover image (optional)", type=["png", "jpg", "jpeg", "webp", "bmp", "gif"])
    form_read = st.checkbox("✅ Mark as read")
    submitted = st.form_submit_button("Add Book")

    if submitted:
        if not form_title.strip() or not form_author.strip():
            st.sidebar.error("Please enter at least the title and author.")
        else:
            saved_cover = save_cover(form_cover) if form_cover else None
            add_book(form_title, form_author, form_genre, form_year, form_read, saved_cover)
            st.sidebar.success(f"Added: {form_title} — {form_author}")
            st.rerun()

st.sidebar.markdown("---")
st.sidebar.markdown("Tips: upload clear covers (jpg/png). Covers are deduplicated by content hash.")

# ------------------- Main UI -------------------

st.title("📚 Personal Library Manager")
st.markdown("Manage your books — add covers, search, filter, toggle read status, and export/import.")

# Filters row
col1, col2, col3, col4 = st.columns([3, 2, 2, 2])
search_input = col1.text_input("🔎 Search by title or author")

genres_list = ["All"] + get_genres()
selected_genre = col2.selectbox("🎯 Genre", genres_list, index=0)

# Compute min/max year from DB for slider defaults 

all_rows = query_books()
years = [r["year"] for r in all_rows if r["year"] is not None]
min_year = min(years) if years else 0
max_year = max(years) if years else datetime.utcnow().year
year_min, year_max = col3.select_slider(
    "📅 Year range",
    options=list(range(0, datetime.utcnow().year + 1)),
    value=(min_year, max_year),
)

read_choice = col4.selectbox("📌 Read status", ["All", "Read", "Unread"])
if read_choice == "All":
    read_filter = None
elif read_choice == "Read":
    read_filter = True
else:
    read_filter = False

st.markdown("---")

# Query books based on filters 

books = query_books(search_text=search_input, genre_filter=selected_genre if selected_genre != "All" else None,
                    year_min=year_min, year_max=year_max, read_filter=read_filter)

left, right = st.columns([3, 1])
left.markdown(f"### 📚 Results — {len(books)} book(s)")
right.markdown("")

if not books:
    st.info("No books found. Add your first book from the sidebar!")
else:
    for b in books:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        cols = st.columns([1, 3, 1])
        with cols[0]:
            if b["cover"] and os.path.exists(b["cover"]):
                try:
                    img = Image.open(b["cover"])
                    st.image(img, width=130)
                except Exception:
                    st.image(Image.new("RGB", (300, 450), "lightgray"), width=130)
            else:
                st.image(Image.new("RGB", (300, 450), "lightgray"), width=130)
        with cols[1]:
            st.markdown(f"### {b['title']}")
            st.markdown(f"**Author:** {b['author']}")
            st.markdown(f"**Genre:** {b['genre'] or 'N/A'}")
            st.markdown(f"**Year:** {b['year'] or 'N/A'}")
            added = b["added_at"][:10] if b["added_at"] else "Unknown"
            st.markdown(f"<p class='meta'>Added: {added}</p>", unsafe_allow_html=True)
            status = "✅ Read" if b["read"] else "📖 Not read yet"
            st.markdown(f"**Status:** {status}")
        with cols[2]:
            if st.button("🔁 Toggle Read", key=f"toggle_{b['id']}"):
                toggle_read(b["id"], not b["read"])
                st.rerun()
            if st.button("🗑️ Delete", key=f"delete_{b['id']}"):
                delete_book(b["id"])
                st.warning(f"Deleted '{b['title']}'")
                st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

# ------------------- Export / Import JSON -------------------
st.markdown("---")
c1, c2 = st.columns(2)

with c1:
    if st.button("📤 Export library (JSON)"):
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT id, title, author, genre, year, read, cover, added_at FROM books")
        rows = cur.fetchall()
        conn.close()
        rows_list = [dict(r) for r in rows]
        st.download_button("Download JSON", data=json.dumps(rows_list, indent=2), file_name="library_export.json", mime="application/json")
        st.success("Export ready for download.")

with c2:
    uploaded = st.file_uploader("📥 Import library (JSON array) - optional", type=["json"])
    if uploaded:
        try:
            payload = json.load(uploaded)
            added = 0
            for item in payload:
                if item.get("title") and item.get("author"):
                    add_book(item.get("title"), item.get("author"), item.get("genre") or "", item.get("year") or None, bool(item.get("read")), None)
                    added += 1
            st.success(f"Imported {added} books.")
            st.rerun()
        except Exception as e:
            st.error("Import failed: Ensure file is a valid JSON array of book objects.")

st.markdown("---")
st.caption("Built with ❤️ using Streamlit — Sanoober")

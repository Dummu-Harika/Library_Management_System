import os
from datetime import datetime, date
from bson import ObjectId
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, flash
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from neo4j import GraphDatabase
from neo4j.exceptions import Neo4jError

load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "change-this-development-key")

# MongoDB connection
mongo_uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
mongo_client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
mongo_db = mongo_client[os.getenv("MONGODB_DB", "library_management")]
books_col = mongo_db["books"]
members_col = mongo_db["members"]
loans_col = mongo_db["loans"]

# Neo4j connection
neo4j_uri = os.getenv("NEO4J_URI", "")
neo4j_user = os.getenv("NEO4J_USERNAME", "neo4j")
neo4j_password = os.getenv("NEO4J_PASSWORD", "")
neo4j_driver = None
if neo4j_uri and neo4j_password:
    try:
        neo4j_driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))
    except Exception as exc:
        print("Neo4j driver initialization failed:", exc)


def neo4j_write(query, **params):
    if not neo4j_driver:
        raise RuntimeError("Neo4j is not configured. Set NEO4J_URI, NEO4J_USERNAME and NEO4J_PASSWORD in .env.")
    with neo4j_driver.session() as session:
        return session.run(query, **params).consume()


def neo4j_read(query, **params):
    if not neo4j_driver:
        raise RuntimeError("Neo4j is not configured. Set NEO4J_URI, NEO4J_USERNAME and NEO4J_PASSWORD in .env.")
    with neo4j_driver.session() as session:
        return [record.data() for record in session.run(query, **params)]


def sync_book_to_graph(book):
    """Keep a Book node and its Author/Genre relationships in Neo4j."""
    title = book["title"].strip()
    author = book["author"].strip()
    genre = book["genre"].strip()
    neo4j_write("""
        MERGE (b:Book {bookId: $book_id})
        SET b.title = $title, b.isbn = $isbn
        MERGE (a:Author {name: $author})
        MERGE (g:Genre {name: $genre})
        MERGE (b)-[:WRITTEN_BY]->(a)
        MERGE (b)-[:BELONGS_TO]->(g)
    """, book_id=str(book["_id"]), title=title, isbn=book.get("isbn", ""),
        author=author, genre=genre)


def sync_member_to_graph(member):
    neo4j_write("""
        MERGE (m:Member {memberId: $member_id})
        SET m.name = $name, m.department = $department
    """, member_id=str(member["_id"]), name=member["name"],
        department=member.get("department", ""))


def get_book(book_id):
    try:
        return books_col.find_one({"_id": ObjectId(book_id)})
    except Exception:
        return None


def get_member(member_id):
    try:
        return members_col.find_one({"_id": ObjectId(member_id)})
    except Exception:
        return None


@app.route("/")
def index():
    try:
        stats = {
            "books": books_col.count_documents({}),
            "available": books_col.count_documents({"available": True}),
            "members": members_col.count_documents({}),
            "active_loans": loans_col.count_documents({"status": "Issued"}),
        }
        recent_books = list(books_col.find().sort("_id", -1).limit(5))
        return render_template("index.html", stats=stats, books=recent_books)
    except PyMongoError as exc:
        return render_template("error.html", message=f"MongoDB connection error: {exc}"), 500


@app.route("/books")
def books():
    q = request.args.get("q", "").strip()
    query = {}
    if q:
        query = {"$or": [
            {"title": {"$regex": q, "$options": "i"}},
            {"author": {"$regex": q, "$options": "i"}},
            {"genre": {"$regex": q, "$options": "i"}},
        ]}
    return render_template("books.html", books=list(books_col.find(query).sort("title", 1)), q=q)


@app.route("/books/add", methods=["GET", "POST"])
def add_book():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        author = request.form.get("author", "").strip()
        genre = request.form.get("genre", "").strip()
        isbn = request.form.get("isbn", "").strip()
        if not title or not author or not genre:
            flash("Title, author, and genre are required.", "error")
            return redirect(url_for("add_book"))
        book = {"title": title, "author": author, "genre": genre, "isbn": isbn,
                "available": True, "created_at": datetime.utcnow()}
        result = books_col.insert_one(book)
        book["_id"] = result.inserted_id
        try:
            sync_book_to_graph(book)
            flash("Book added to MongoDB and synced to Neo4j.", "success")
        except Exception as exc:
            flash(f"Book saved in MongoDB, but Neo4j sync failed: {exc}", "warning")
        return redirect(url_for("books"))
    return render_template("book_form.html", book=None)


@app.route("/books/<book_id>/edit", methods=["GET", "POST"])
def edit_book(book_id):
    book = get_book(book_id)
    if not book:
        flash("Book not found.", "error")
        return redirect(url_for("books"))
    if request.method == "POST":
        updated = {
            "title": request.form.get("title", "").strip(),
            "author": request.form.get("author", "").strip(),
            "genre": request.form.get("genre", "").strip(),
            "isbn": request.form.get("isbn", "").strip(),
        }
        if not all(updated[k] for k in ("title", "author", "genre")):
            flash("Title, author, and genre are required.", "error")
            return redirect(url_for("edit_book", book_id=book_id))
        books_col.update_one({"_id": book["_id"]}, {"$set": updated})
        book.update(updated)
        try:
            sync_book_to_graph(book)
            flash("Book updated in MongoDB and Neo4j.", "success")
        except Exception as exc:
            flash(f"Book updated in MongoDB, but Neo4j sync failed: {exc}", "warning")
        return redirect(url_for("books"))
    return render_template("book_form.html", book=book)


@app.post("/books/<book_id>/delete")
def delete_book(book_id):
    book = get_book(book_id)
    if not book:
        flash("Book not found.", "error")
        return redirect(url_for("books"))
    if loans_col.count_documents({"book_id": str(book["_id"]), "status": "Issued"}):
        flash("Cannot delete a book while it is currently issued.", "error")
        return redirect(url_for("books"))
    books_col.delete_one({"_id": book["_id"]})
    try:
        neo4j_write("MATCH (b:Book {bookId: $book_id}) DETACH DELETE b", book_id=str(book["_id"]))
        flash("Book deleted from MongoDB and Neo4j.", "success")
    except Exception as exc:
        flash(f"Book deleted from MongoDB, but Neo4j cleanup failed: {exc}", "warning")
    return redirect(url_for("books"))


@app.route("/members")
def members():
    return render_template("members.html", members=list(members_col.find().sort("name", 1)))


@app.route("/members/add", methods=["GET", "POST"])
def add_member():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        department = request.form.get("department", "").strip()
        if not name or not email:
            flash("Name and email are required.", "error")
            return redirect(url_for("add_member"))
        if members_col.find_one({"email": email}):
            flash("A member with this email already exists.", "error")
            return redirect(url_for("add_member"))
        member = {"name": name, "email": email, "department": department,
                  "created_at": datetime.utcnow()}
        result = members_col.insert_one(member)
        member["_id"] = result.inserted_id
        try:
            sync_member_to_graph(member)
            flash("Member added to MongoDB and Neo4j.", "success")
        except Exception as exc:
            flash(f"Member saved in MongoDB, but Neo4j sync failed: {exc}", "warning")
        return redirect(url_for("members"))
    return render_template("member_form.html", member=None)


@app.route("/members/<member_id>/edit", methods=["GET", "POST"])
def edit_member(member_id):
    member = get_member(member_id)
    if not member:
        flash("Member not found.", "error")
        return redirect(url_for("members"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        department = request.form.get("department", "").strip()
        if not name or not email:
            flash("Name and email are required.", "error")
            return redirect(url_for("edit_member", member_id=member_id))
        duplicate = members_col.find_one({"email": email, "_id": {"$ne": member["_id"]}})
        if duplicate:
            flash("Another member already uses this email.", "error")
            return redirect(url_for("edit_member", member_id=member_id))
        members_col.update_one({"_id": member["_id"]},
                               {"$set": {"name": name, "email": email, "department": department}})
        try:
            sync_member_to_graph({"_id": member["_id"], "name": name, "department": department})
            flash("Member updated in MongoDB and Neo4j.", "success")
        except Exception as exc:
            flash(f"Member updated in MongoDB, but Neo4j sync failed: {exc}", "warning")
        return redirect(url_for("members"))
    return render_template("member_form.html", member=member)


@app.post("/members/<member_id>/delete")
def delete_member(member_id):
    member = get_member(member_id)
    if not member:
        flash("Member not found.", "error")
        return redirect(url_for("members"))
    if loans_col.count_documents({"member_id": str(member["_id"]), "status": "Issued"}):
        flash("Return this member's issued books before deleting the member.", "error")
        return redirect(url_for("members"))
    members_col.delete_one({"_id": member["_id"]})
    try:
        neo4j_write("MATCH (m:Member {memberId: $member_id}) DETACH DELETE m",
                    member_id=str(member["_id"]))
        flash("Member deleted from MongoDB and Neo4j.", "success")
    except Exception as exc:
        flash(f"Member deleted in MongoDB, but Neo4j cleanup failed: {exc}", "warning")
    return redirect(url_for("members"))


@app.route("/loans")
def loans():
    all_loans = list(loans_col.find().sort("_id", -1))
    for loan in all_loans:
        loan["book"] = books_col.find_one({"_id": ObjectId(loan["book_id"])}) if ObjectId.is_valid(loan["book_id"]) else None
        loan["member"] = members_col.find_one({"_id": ObjectId(loan["member_id"])}) if ObjectId.is_valid(loan["member_id"]) else None
    return render_template("loans.html", loans=all_loans,
                           books=list(books_col.find({"available": True}).sort("title", 1)),
                           members=list(members_col.find().sort("name", 1)))


@app.post("/loans/issue")
def issue_book():
    book = get_book(request.form.get("book_id", ""))
    member = get_member(request.form.get("member_id", ""))
    due_date = request.form.get("due_date", "")
    if not book or not member:
        flash("Choose a valid book and member.", "error")
        return redirect(url_for("loans"))
    if not book.get("available", True):
        flash("This book is already issued.", "error")
        return redirect(url_for("loans"))
    try:
        datetime.strptime(due_date, "%Y-%m-%d")
    except ValueError:
        flash("Choose a valid due date.", "error")
        return redirect(url_for("loans"))
    loan = {"book_id": str(book["_id"]), "member_id": str(member["_id"]),
            "issue_date": date.today().isoformat(), "due_date": due_date,
            "return_date": None, "status": "Issued"}
    loans_col.insert_one(loan)
    books_col.update_one({"_id": book["_id"]}, {"$set": {"available": False}})
    try:
        neo4j_write("""
            MATCH (m:Member {memberId: $member_id})
            MATCH (b:Book {bookId: $book_id})
            MERGE (m)-[r:BORROWED]->(b)
            SET r.issueDate = $issue_date, r.dueDate = $due_date, r.status = 'Issued'
        """, member_id=str(member["_id"]), book_id=str(book["_id"]),
            issue_date=loan["issue_date"], due_date=due_date)
        flash("Book issued. MongoDB transaction and Neo4j relationship created.", "success")
    except Exception as exc:
        flash(f"Loan saved in MongoDB, but Neo4j relationship failed: {exc}", "warning")
    return redirect(url_for("loans"))


@app.post("/loans/<loan_id>/return")
def return_book(loan_id):
    try:
        loan = loans_col.find_one({"_id": ObjectId(loan_id)})
    except Exception:
        loan = None
    if not loan or loan["status"] != "Issued":
        flash("Active loan not found.", "error")
        return redirect(url_for("loans"))
    loans_col.update_one({"_id": loan["_id"]},
                         {"$set": {"status": "Returned", "return_date": date.today().isoformat()}})
    books_col.update_one({"_id": ObjectId(loan["book_id"])}, {"$set": {"available": True}})
    try:
        neo4j_write("""
            MATCH (m:Member {memberId: $member_id})-[r:BORROWED]->(b:Book {bookId: $book_id})
            SET r.status = 'Returned', r.returnDate = $return_date
        """, member_id=loan["member_id"], book_id=loan["book_id"],
            return_date=date.today().isoformat())
        flash("Book returned and both databases updated.", "success")
    except Exception as exc:
        flash(f"Return saved in MongoDB, but Neo4j update failed: {exc}", "warning")
    return redirect(url_for("loans"))


@app.route("/recommendations")
def recommendations():
    member_id = request.args.get("member_id", "")
    members_list = list(members_col.find().sort("name", 1))
    results = []
    error = None
    if member_id:
        try:
            results = neo4j_read("""
                MATCH (m:Member {memberId: $member_id})-[:BORROWED]->(past:Book)
                      -[:BELONGS_TO]->(g:Genre)<-[:BELONGS_TO]-(rec:Book)
                WHERE NOT (m)-[:BORROWED]->(rec)
                WITH DISTINCT rec, g
                RETURN rec.title AS title, rec.bookId AS book_id,
                       collect(DISTINCT g.name) AS reasons
                ORDER BY title
            """, member_id=member_id)
            # A member may have no borrow history; show genre-based alternatives only when history exists.
        except Exception as exc:
            error = str(exc)
    return render_template("recommendations.html", members=members_list,
                           selected_member=member_id, recommendations=results, error=error)


@app.route("/health")
def health():
    status = {"flask": "ok", "mongodb": "unknown", "neo4j": "not configured"}
    try:
        mongo_client.admin.command("ping")
        status["mongodb"] = "connected"
    except Exception as exc:
        status["mongodb"] = f"error: {exc}"
    if neo4j_driver:
        try:
            neo4j_driver.verify_connectivity()
            status["neo4j"] = "connected"
        except Exception as exc:
            status["neo4j"] = f"error: {exc}"
    return status


@app.errorhandler(500)
def internal_error(error):
    return render_template("error.html", message="An unexpected error occurred. Check the Flask terminal for details."), 500


if __name__ == "__main__":
    app.run(debug=True)

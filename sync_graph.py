
import os
from dotenv import load_dotenv
from pymongo import MongoClient
from neo4j import GraphDatabase

load_dotenv(override=True)

mongo = MongoClient(os.environ["MONGODB_URI"])
db = mongo[os.getenv("MONGODB_DB", "library_management")]

driver = GraphDatabase.driver(
    os.environ["NEO4J_URI"],
    auth=(
        os.environ["NEO4J_USERNAME"],
        os.environ["NEO4J_PASSWORD"]
    )
)

try:
    with driver.session() as session:
        # Sync existing members
        for member in db.members.find():
            session.run("""
                MERGE (m:Member {memberId: $id})
                SET m.name = $name,
                    m.department = $department
            """,
                id=str(member["_id"]),
                name=member["name"],
                department=member.get("department", "")
            )

        # Sync existing books
        for book in db.books.find():
            session.run("""
                MERGE (b:Book {bookId: $id})
                SET b.title = $title, b.isbn = $isbn
                MERGE (a:Author {name: $author})
                MERGE (g:Genre {name: $genre})
                MERGE (b)-[:WRITTEN_BY]->(a)
                MERGE (b)-[:BELONGS_TO]->(g)
            """,
                id=str(book["_id"]),
                title=book["title"],
                isbn=book.get("isbn", ""),
                author=book["author"],
                genre=book["genre"]
            )

        # Sync existing loans, including returned loans
        for loan in db.loans.find():
            session.run("""
                MATCH (m:Member {memberId: $member_id})
                MATCH (b:Book {bookId: $book_id})
                MERGE (m)-[r:BORROWED]->(b)
                SET r.status = $status,
                    r.issueDate = $issue_date,
                    r.dueDate = $due_date
            """,
                member_id=loan["member_id"],
                book_id=loan["book_id"],
                status=loan["status"],
                issue_date=loan.get("issue_date", ""),
                due_date=loan.get("due_date", "")
            )

    print("Graph synchronization finished.")
finally:
    driver.close()
    mongo.close()

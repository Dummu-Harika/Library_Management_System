// 1. View every book and its genre
MATCH (b:Book)-[:BELONGS_TO]->(g:Genre)
RETURN b.title AS Book, g.name AS Genre;

// 2. View book-author relationships
MATCH (b:Book)-[:WRITTEN_BY]->(a:Author)
RETURN b.title AS Book, a.name AS Author;

// 3. View member borrowing relationships
MATCH (m:Member)-[r:BORROWED]->(b:Book)
RETURN m.name AS Member, b.title AS Book, r.status AS Status;

// 4. Find books in genres the member has borrowed before
MATCH (m:Member {memberId: 'REPLACE_WITH_MEMBER_OBJECT_ID'})-[:BORROWED]->(past:Book)
      -[:BELONGS_TO]->(g:Genre)<-[:BELONGS_TO]-(rec:Book)
WHERE NOT (m)-[:BORROWED]->(rec)
RETURN DISTINCT rec.title AS Recommendation, g.name AS SharedGenre;

// 5. Count books by genre
MATCH (b:Book)-[:BELONGS_TO]->(g:Genre)
RETURN g.name AS Genre, count(b) AS NumberOfBooks
ORDER BY NumberOfBooks DESC;

// 6. Delete a book node and its relationships (use with care)
// MATCH (b:Book {bookId: 'REPLACE_WITH_BOOK_OBJECT_ID'}) DETACH DELETE b;

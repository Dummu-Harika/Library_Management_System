# Library Management and Book Recommendation System

A Flask-based NoSQL PBL starter project using MongoDB and Neo4j.

## Features
- Book CRUD (MongoDB + Neo4j sync)
- Member CRUD (MongoDB + Neo4j sync)
- Issue/return workflow and borrowing history (MongoDB + Neo4j relationship)
- Genre-based recommendations using Neo4j
- Dashboard and connection health endpoint

## Requirements
- Python 3.10+
- MongoDB Atlas or local MongoDB
- Neo4j Aura or local Neo4j

## Setup (Windows)
1. Extract the ZIP and open Command Prompt in the `library_management_pbl` folder.
2. Create a virtual environment:
   ```bat
   py -m venv .venv
   .venv\Scripts\activate
   ```
3. Install packages:
   ```bat
   pip install -r requirements.txt
   ```
4. Copy `.env.example` to `.env`.
   ```bat
   copy .env.example .env
   ```
5. Edit `.env` with your actual MongoDB and Neo4j connection values. Do not share the `.env` file or passwords.
6. Run:
   ```bat
   python app.py
   ```
7. Open http://127.0.0.1:5000

## Pages
- `/` dashboard
- `/books` book catalog and search
- `/members` member management
- `/loans` issue and return books
- `/recommendations` choose a member for recommendations
- `/health` connection status

## Neo4j verification queries
```cypher
MATCH (b:Book)-[r]->(x)
RETURN b, r, x;
```
```cypher
MATCH (m:Member)-[r:BORROWED]->(b:Book)
RETURN m, r, b;
```
```cypher
MATCH (b:Book)-[:BELONGS_TO]->(g:Genre)
RETURN b.title AS Book, g.name AS Genre;
```

## Important notes
- This is an educational starter, not a production-ready system.
- Test with sample data first. Book/member data is written to MongoDB and then synchronized to Neo4j; the two databases do not share a distributed transaction. The UI reports sync failures so you can correct them.
- Recommendations require the member to have borrowed at least one book and the graph to contain other books in the same genre.
- Use a strong Flask secret key and keep `.env` private.

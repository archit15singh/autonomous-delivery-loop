"""Consume the pilot queue and store job completion in its SQLite database."""
import re
import socket
import sqlite3
import time


def pop():
    with socket.create_connection(("127.0.0.1", 6379), timeout=2) as redis:
        redis.sendall(b"*2\r\n$4\r\nLPOP\r\n$8\r\nadl:jobs\r\n")
        with redis.makefile("rb") as response:
            size = response.readline(32)
            if size == b"$-1\r\n":
                return None
            if size != b"$32\r\n":
                raise ValueError("unexpected pilot queue item size")
            job = response.read(34)
            if not re.fullmatch(rb"[a-f0-9]{32}\r\n", job):
                raise ValueError("invalid pilot job")
            return job[:-2].decode()


def main():
    with sqlite3.connect("/data/jobs.sqlite3") as db:
        db.execute("CREATE TABLE jobs (id TEXT PRIMARY KEY, status TEXT NOT NULL)")
        while True:
            job = pop()
            if job is not None:
                db.execute("INSERT INTO jobs VALUES (?, 'completed')", (job,))
                db.commit()
            time.sleep(0.05)


if __name__ == "__main__":
    main()

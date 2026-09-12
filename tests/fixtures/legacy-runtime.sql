CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, plan TEXT NOT NULL, status TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS assignments(id TEXT PRIMARY KEY, run TEXT NOT NULL, task TEXT NOT NULL,
            version INTEGER NOT NULL, spec TEXT NOT NULL, UNIQUE(run,task,version));
        CREATE TABLE IF NOT EXISTS tasks(run TEXT NOT NULL, id TEXT NOT NULL, assignment TEXT NOT NULL,
            status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, latest TEXT, PRIMARY KEY(run,id));
        CREATE TABLE IF NOT EXISTS attempts(id TEXT PRIMARY KEY, run TEXT NOT NULL, task TEXT NOT NULL,
            assignment TEXT NOT NULL, state TEXT NOT NULL, resource TEXT, frozen TEXT NOT NULL,
            session TEXT NOT NULL, receipt TEXT, error TEXT);
        CREATE TABLE IF NOT EXISTS artifacts(id TEXT PRIMARY KEY, run TEXT, task TEXT, attempt TEXT,
            path TEXT NOT NULL, blob TEXT NOT NULL, sha256 TEXT NOT NULL, bytes INTEGER NOT NULL,
            purpose TEXT NOT NULL, source TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, created REAL NOT NULL, run TEXT,
            task TEXT, attempt TEXT, kind TEXT NOT NULL, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS decisions(id TEXT PRIMARY KEY, run TEXT NOT NULL, task TEXT NOT NULL,
            artifact TEXT NOT NULL, purpose TEXT NOT NULL, note TEXT NOT NULL, created REAL NOT NULL);

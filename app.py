import json
import os
import sqlite3
from datetime import datetime, timezone
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify, g
)
from werkzeug.security import generate_password_hash, check_password_hash

from services.skill_gap import analyze_gaps

from services.readiness import calculate_readiness

from services.readiness_updates import blend_assessment_with_quiz_scores
from services.recommendations import recommend_projects


BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATABASE = os.path.join(BASE_DIR, "database", "skill_gap.db")

app = Flask(__name__)
app.secret_key = os.environ.get(
    "SECRET_KEY", "dev-only-change-this-secret-key"
)
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024


# ---------------------------------------------------------
# ROLE REQUIREMENTS
# ---------------------------------------------------------

ROLE_REQUIREMENTS = {
    "Software Developer": {
        "Python": 70, "Java": 70, "DSA": 75,
        "SQL": 65, "Aptitude": 70
    },
    "Data Analyst": {
        "Python": 70, "SQL": 80, "Data Visualization": 75,
        "Statistics": 70, "Aptitude": 65
    },
    "Cybersecurity Analyst": {
        "Networking": 75, "Linux": 70,
        "Security Fundamentals": 80, "Python": 60,
        "Aptitude": 65
    },
    "Web Developer": {
        "HTML/CSS": 75, "JavaScript": 75,
        "Python": 60, "SQL": 60, "Aptitude": 60
    },
    "Python Developer": {
        "Python": 80, "DSA": 70, "SQL": 65,
        "Statistics": 55, "Aptitude": 65
    },
    "Java Developer": {
        "Java": 80, "DSA": 75, "SQL": 65,
        "Python": 55, "Aptitude": 65
    },
    "AI/ML Engineer": {
        "Python": 80, "Statistics": 75,
        "Data Visualization": 65, "DSA": 65, "SQL": 60
    },
    "Cloud Engineer": {
        "Networking": 75, "Linux": 75,
        "Security Fundamentals": 70, "Python": 60, "SQL": 55
    },
    "DevOps Engineer": {
        "Linux": 75, "Networking": 70, "Python": 65,
        "DSA": 55, "SQL": 55
    },
    "UI/UX Designer": {
        "UI/UX Design": 80, "HTML/CSS": 65,
        "Data Visualization": 60, "Aptitude": 60, "Statistics": 50
    },
    "Mobile App Developer": {
        "Java": 75, "Python": 55, "DSA": 70,
        "SQL": 60, "UI/UX Design": 60
    },
}

DEFAULT_SKILLS = {
    role: list(requirements.keys())
    for role, requirements in ROLE_REQUIREMENTS.items()
}

READINESS_WEIGHTS = {
    "Programming Skills": 20,
    "DSA": 20,
    "SQL": 15,
    "Aptitude": 15,
    "Projects": 15,
    "Certifications / Internships": 5,
    "Resume / Profile Completeness": 10,
}


# ---------------------------------------------------------
# COURSE ANALYZER QUESTION BANK
# ---------------------------------------------------------

QUIZ_BANK = {
    "Python": [
        {
            "q": "Which Python collection stores unique values?",
            "options": ["list", "tuple", "set", "dict"],
            "answer": 2,
            "explanation": "A set stores unique elements."
        },
        {
            "q": "What does len([2, 4, 6]) return?",
            "options": ["2", "3", "4", "6"],
            "answer": 1,
            "explanation": "The list contains three items."
        },
        {
            "q": "Which keyword defines a function?",
            "options": ["func", "define", "def", "function"],
            "answer": 2,
            "explanation": "Python functions are declared with def."
        },
    ],
    "Java": [
        {
            "q": "Which keyword creates a subclass in Java?",
            "options": ["implements", "extends", "inherits", "superclass"],
            "answer": 1,
            "explanation": "A class extends another class."
        },
        {
            "q": "Which type stores true or false?",
            "options": ["int", "String", "boolean", "char"],
            "answer": 2,
            "explanation": "boolean represents true/false values."
        },
        {
            "q": "Which method is the usual Java program entry point?",
            "options": ["run()", "start()", "main()", "init()"],
            "answer": 2,
            "explanation": "The entry point is main(String[] args)."
        },
    ],
    "DSA": [
        {
            "q": "What is binary search's average time complexity?",
            "options": ["O(n)", "O(log n)", "O(n²)", "O(1) always"],
            "answer": 1,
            "explanation": "Binary search halves the search space each step."
        },
        {
            "q": "Which structure follows FIFO?",
            "options": ["Stack", "Queue", "Tree", "Graph"],
            "answer": 1,
            "explanation": "A queue is first-in, first-out."
        },
        {
            "q": "Which traversal uses a queue in an unweighted graph?",
            "options": ["DFS", "BFS", "Inorder", "Backtracking only"],
            "answer": 1,
            "explanation": "BFS uses a queue to explore by levels."
        },
    ],
    "SQL": [
        {
            "q": "Which SQL command retrieves rows?",
            "options": ["GET", "SELECT", "OPEN", "FETCH ALL"],
            "answer": 1,
            "explanation": "SELECT queries data from tables or views."
        },
        {
            "q": "Which clause filters grouped results?",
            "options": ["WHERE", "ORDER BY", "HAVING", "LIMIT"],
            "answer": 2,
            "explanation": "HAVING filters groups after aggregation."
        },
        {
            "q": "Which key uniquely identifies a row?",
            "options": ["Foreign key", "Primary key", "Index only", "Duplicate key"],
            "answer": 1,
            "explanation": "A primary key uniquely identifies each row."
        },
    ],
    "Aptitude": [
        {
            "q": "A product costs ₹800 after a 20% discount. Original price?",
            "options": ["₹960", "₹1,000", "₹1,020", "₹1,200"],
            "answer": 1,
            "explanation": "800 is 80% of the original, so 800 / 0.8 = 1000."
        },
        {
            "q": "What is the next number: 3, 6, 12, 24, ...?",
            "options": ["30", "36", "48", "60"],
            "answer": 2,
            "explanation": "Each term doubles, so the next is 48."
        },
        {
            "q": "A car travels 150 km in 3 hours. Average speed?",
            "options": ["30 km/h", "45 km/h", "50 km/h", "60 km/h"],
            "answer": 2,
            "explanation": "Speed = distance / time = 150 / 3 = 50 km/h."
        },
    ],
    "Data Visualization": [
        {
            "q": "Which chart is usually best for comparing categories?",
            "options": ["Bar chart", "Scatter plot only", "Map always", "Gauge only"],
            "answer": 0,
            "explanation": "Bar charts make category comparisons clear."
        },
        {
            "q": "What does a scatter plot help reveal?",
            "options": [
                "Only totals", "Relationship between numeric variables",
                "Text spelling", "Database keys"
            ],
            "answer": 1,
            "explanation": "Scatter plots show relationships and correlation patterns."
        },
        {
            "q": "Which practice improves chart accessibility?",
            "options": [
                "Use color alone", "Remove labels",
                "Add clear labels and contrast", "Hide units"
            ],
            "answer": 2,
            "explanation": "Labels, units, and contrast improve interpretation."
        },
    ],
    "Statistics": [
        {
            "q": "Which measure is most affected by extreme outliers?",
            "options": ["Median", "Mean", "Mode", "Quartile rank"],
            "answer": 1,
            "explanation": "The mean is sensitive to extreme values."
        },
        {
            "q": "What is the probability of a fair coin landing heads?",
            "options": ["0", "0.25", "0.5", "1"],
            "answer": 2,
            "explanation": "There are two equally likely outcomes."
        },
        {
            "q": "Standard deviation measures what?",
            "options": [
                "Central value only", "Spread around the mean",
                "Sample name", "Causation"
            ],
            "answer": 1,
            "explanation": "Standard deviation measures dispersion."
        },
    ],
    "Networking": [
        {
            "q": "Which protocol translates domain names to IP addresses?",
            "options": ["DNS", "FTP", "SMTP", "SSH"],
            "answer": 0,
            "explanation": "DNS resolves names to IP addresses."
        },
        {
            "q": "Which protocol is connection-oriented?",
            "options": ["UDP", "TCP", "IP only", "ARP"],
            "answer": 1,
            "explanation": "TCP provides connection-oriented reliable delivery."
        },
        {
            "q": "Which device forwards packets between networks?",
            "options": ["Router", "Keyboard", "Repeater only", "Monitor"],
            "answer": 0,
            "explanation": "Routers forward packets between networks."
        },
    ],
    "Linux": [
        {
            "q": "Which command lists files in a directory?",
            "options": ["ls", "pwd", "cd", "whoami"],
            "answer": 0,
            "explanation": "ls lists directory contents."
        },
        {
            "q": "Which command changes file permissions?",
            "options": ["chown", "chmod", "grep", "touch"],
            "answer": 1,
            "explanation": "chmod changes permission bits."
        },
        {
            "q": "Which command prints the current directory?",
            "options": ["pwd", "ps", "cat", "mkdir"],
            "answer": 0,
            "explanation": "pwd prints the current working directory."
        },
    ],
    "Security Fundamentals": [
        {
            "q": "What does MFA add to authentication?",
            "options": [
                "An additional verification factor", "A public folder",
                "A faster CPU", "A database index"
            ],
            "answer": 0,
            "explanation": "MFA combines two or more different factor types."
        },
        {
            "q": "What is phishing?",
            "options": [
                "A backup method", "A deceptive attempt to steal information",
                "A network cable", "A hashing algorithm"
            ],
            "answer": 1,
            "explanation": "Phishing tricks users into disclosing information."
        },
        {
            "q": "Why are software security patches important?",
            "options": [
                "They remove all risk forever",
                "They address known vulnerabilities",
                "They replace backups", "They disable authentication"
            ],
            "answer": 1,
            "explanation": "Patches fix known flaws that attackers may exploit."
        },
    ],
    "HTML/CSS": [
        {
            "q": "Which HTML element represents the main heading?",
            "options": ["<h1>", "<head>", "<title>", "<p>"],
            "answer": 0,
            "explanation": "h1 is the top-level heading element."
        },
        {
            "q": "Which CSS property changes text color?",
            "options": ["font-style", "color", "background-image", "display"],
            "answer": 1,
            "explanation": "The color property sets foreground text color."
        },
        {
            "q": "Which layout system is designed for rows or columns?",
            "options": ["Flexbox", "SQL", "DNS", "JSON"],
            "answer": 0,
            "explanation": "Flexbox lays out items along a row or column."
        },
    ],
    "JavaScript": [
        {
            "q": "Which keyword declares a reassignable block-scoped variable?",
            "options": ["const", "let", "static", "define"],
            "answer": 1,
            "explanation": "let declares a block-scoped variable."
        },
        {
            "q": "What does document.querySelector() return?",
            "options": [
                "The first matching element", "Every element as an array",
                "A database row", "A CSS file"
            ],
            "answer": 0,
            "explanation": "querySelector returns the first matching element."
        },
        {
            "q": "Which method parses JSON text into a JavaScript value?",
            "options": ["JSON.parse()", "JSON.stringify()", "JSON.open()", "JSON.read()"],
            "answer": 0,
            "explanation": "JSON.parse parses JSON text into a value."
        },
    ],
    "UI/UX Design": [
        {
            "q": "What is the main purpose of a wireframe?",
            "options": [
                "Define layout and structure", "Store passwords",
                "Compile Java code", "Configure DNS"
            ],
            "answer": 0,
            "explanation": "Wireframes communicate screen structure and hierarchy."
        },
        {
            "q": "What is usability testing used for?",
            "options": [
                "Observe people completing tasks with a design",
                "Increase image file size", "Replace all user research",
                "Write SQL queries"
            ],
            "answer": 0,
            "explanation": "Usability tests identify where users struggle."
        },
        {
            "q": "Which practice helps make a UI more accessible?",
            "options": [
                "Low contrast text", "Meaningful labels and keyboard access",
                "Color as the only signal", "Tiny clickable targets"
            ],
            "answer": 1,
            "explanation": "Labels and keyboard access help more people use a UI."
        },
    ],
}


# ---------------------------------------------------------
# ROLE-SPECIFIC LEARNING SYLLABUS
# Each role has Week 0 through Week 4.
# ---------------------------------------------------------

ROLE_SYLLABUS = {
    "Software Developer": [
        ("Programming Foundations", [
            "Variables, data types and operators",
            "Conditions, loops, functions and debugging",
            "Basic problem-solving exercises"
        ]),
        ("Object-Oriented Programming", [
            "Classes and objects",
            "Inheritance, polymorphism and encapsulation",
            "Exceptions and file handling"
        ]),
        ("Data Structures and Algorithms", [
            "Arrays, strings and linked lists",
            "Stacks, queues, hash maps and trees",
            "Searching, sorting and Big-O complexity"
        ]),
        ("Databases and SQL", [
            "Relational database concepts",
            "SELECT, JOIN, GROUP BY and subqueries",
            "Keys, normalization and transactions"
        ]),
        ("Software Engineering Project", [
            "Git and version control",
            "Unit testing and debugging",
            "REST APIs and a portfolio project"
        ]),
    ],
    "Data Analyst": [
        ("Python for Data Analysis", [
            "Python collections and functions",
            "NumPy arrays and vector operations",
            "Pandas data cleaning and grouping"
        ]),
        ("SQL for Analytics", [
            "SELECT, WHERE and ORDER BY",
            "JOIN, GROUP BY and HAVING",
            "Subqueries, CTEs and window functions"
        ]),
        ("Statistics", [
            "Mean, median, variance and standard deviation",
            "Probability and distributions",
            "Correlation and hypothesis testing"
        ]),
        ("Data Visualization", [
            "Selecting suitable charts",
            "Matplotlib and dashboard fundamentals",
            "KPIs and communicating insights"
        ]),
        ("Analytics Project", [
            "Clean a real dataset",
            "Build a dashboard",
            "Write findings and recommendations"
        ]),
    ],
    "Cybersecurity Analyst": [
        ("Networking Essentials", [
            "OSI and TCP/IP models",
            "IP addressing, subnetting, DNS and HTTP/S",
            "Ports, routing, firewalls and packet analysis"
        ]),
        ("Linux and Scripting", [
            "Linux files, permissions and processes",
            "Shell commands, logs and services",
            "Python automation scripts"
        ]),
        ("Security Fundamentals", [
            "Confidentiality, integrity and availability",
            "Threats, vulnerabilities and risk",
            "MFA, access control and cryptography"
        ]),
        ("Defensive Security", [
            "Security logs and SIEM concepts",
            "Incident response lifecycle",
            "Vulnerability assessment and remediation"
        ]),
        ("Security Lab Project", [
            "Threat-model a sample application",
            "Investigate sample logs in a local lab",
            "Write an incident report"
        ]),
    ],
    "Web Developer": [
        ("HTML and CSS", [
            "Semantic HTML and accessible forms",
            "CSS box model, Flexbox and Grid",
            "Responsive design and media queries"
        ]),
        ("JavaScript Fundamentals", [
            "Variables, functions and arrays",
            "DOM manipulation and event handling",
            "Form validation and asynchronous JavaScript"
        ]),
        ("Frontend Development", [
            "Consume REST APIs",
            "Loading, error and empty states",
            "Accessibility and browser debugging"
        ]),
        ("Backend and Databases", [
            "HTTP methods and status codes",
            "SQL CRUD operations",
            "Input validation and authentication"
        ]),
        ("Portfolio Website", [
            "Build responsive pages",
            "Connect a form to an API",
            "Deploy and document the project"
        ]),
    ],
    "Python Developer": [
        ("Python Core", [
            "Types, collections and comprehensions",
            "Functions, modules and packages",
            "Exceptions and file handling"
        ]),
        ("Intermediate Python", [
            "Object-oriented programming",
            "Iterators, generators and decorators",
            "Virtual environments and dependencies"
        ]),
        ("Algorithms and Testing", [
            "Searching, sorting and complexity",
            "Unit testing fundamentals",
            "Logging, debugging and type hints"
        ]),
        ("APIs and Databases", [
            "HTTP and REST API concepts",
            "Flask routes and request validation",
            "SQLite and SQL queries"
        ]),
        ("Python Project", [
            "Build a CRUD API",
            "Add tests and error handling",
            "Document setup and usage"
        ]),
    ],
    "Java Developer": [
        ("Java Fundamentals", [
            "Types, operators and control flow",
            "Arrays, strings and collections",
            "Classes, constructors and packages"
        ]),
        ("Object-Oriented Java", [
            "Encapsulation, inheritance and polymorphism",
            "Interfaces and abstract classes",
            "Exceptions and generics"
        ]),
        ("Collections and Concurrency", [
            "List, Set and Map",
            "Threads and synchronization basics",
            "Streams and lambda expressions"
        ]),
        ("Databases and APIs", [
            "JDBC and prepared statements",
            "SQL joins and transactions",
            "REST APIs and JSON"
        ]),
        ("Java Application", [
            "Layered application structure",
            "Unit tests and logging",
            "Build and document an application"
        ]),
    ],
    "AI/ML Engineer": [
        ("Python and Data", [
            "Python functions and data structures",
            "NumPy and Pandas",
            "Data cleaning and exploratory analysis"
        ]),
        ("Mathematics and Statistics", [
            "Vectors, matrices and dot products",
            "Probability and distributions",
            "Variance, correlation and gradients"
        ]),
        ("Machine Learning", [
            "Supervised and unsupervised learning",
            "Regression and classification",
            "Clustering and feature engineering"
        ]),
        ("Model Evaluation", [
            "Training, validation and test sets",
            "Accuracy, precision, recall and F1-score",
            "Overfitting and cross-validation"
        ]),
        ("Machine Learning Project", [
            "Build a baseline model",
            "Compare evaluation metrics",
            "Document limitations and results"
        ]),
    ],
    "Cloud Engineer": [
        ("Cloud Foundations", [
            "IaaS, PaaS and SaaS",
            "Regions, availability zones and shared responsibility",
            "Compute, storage and managed databases"
        ]),
        ("Linux and Networking", [
            "Linux processes and permissions",
            "CIDR, DNS, routing and firewalls",
            "TLS and network troubleshooting"
        ]),
        ("Cloud Security", [
            "IAM roles and least privilege",
            "Secrets management and encryption",
            "Backups, monitoring and audit logs"
        ]),
        ("Deployment and Operations", [
            "Virtual machines and containers",
            "Infrastructure-as-code concepts",
            "Logs, alerts and cost controls"
        ]),
        ("Cloud Project", [
            "Deploy a small web application",
            "Configure access and monitoring",
            "Document architecture and recovery steps"
        ]),
    ],
    "DevOps Engineer": [
        ("Linux and Scripting", [
            "Shell navigation and permissions",
            "Bash or Python automation",
            "Logs and service management"
        ]),
        ("Git Workflows", [
            "Branches, commits and pull requests",
            "Merge conflicts and code review",
            "Releases and rollback concepts"
        ]),
        ("CI/CD", [
            "Build and test pipeline stages",
            "Environment variables and secrets",
            "Deployment gates and rollback"
        ]),
        ("Containers and Cloud", [
            "Docker images and containers",
            "Volumes and container networking",
            "Cloud deployment fundamentals"
        ]),
        ("DevOps Project", [
            "Automate tests and builds",
            "Deploy a sample service",
            "Add health checks and logging"
        ]),
    ],
    "UI/UX Designer": [
        ("Design Fundamentals", [
            "User needs and problem framing",
            "Visual hierarchy, spacing and typography",
            "Color contrast and accessibility"
        ]),
        ("Research and User Flows", [
            "User interviews and assumptions",
            "Personas and journey maps",
            "Information architecture and task flows"
        ]),
        ("Wireframes and Prototypes", [
            "Low-fidelity wireframes",
            "Reusable components and design systems",
            "Interactive prototypes and usability testing"
        ]),
        ("Developer Handoff", [
            "Responsive behavior and interface states",
            "Design tokens and component specifications",
            "Accessibility annotations and assets"
        ]),
        ("UX Case Study", [
            "Define a user problem",
            "Prototype and test a solution",
            "Present design decisions and findings"
        ]),
    ],
    "Mobile App Developer": [
        ("Mobile Foundations", [
            "Mobile layouts and navigation",
            "Application lifecycle and state",
            "Responsive layouts and accessibility"
        ]),
        ("Programming and Architecture", [
            "Classes, functions and asynchronous work",
            "MVVM or layered architecture",
            "State management and error handling"
        ]),
        ("Data and APIs", [
            "REST APIs and JSON",
            "Local storage and SQLite concepts",
            "Authentication and secure token storage"
        ]),
        ("Quality and Release", [
            "Unit and UI testing",
            "Performance, permissions and privacy",
            "Build variants and release checklist"
        ]),
        ("Mobile Project", [
            "Build a multi-screen app",
            "Connect an API and persist data",
            "Test different screen sizes"
        ]),
    ],
}


def build_role_roadmap(role, gaps=None):
    """Build five role-specific tasks numbered Week 0 through Week 4."""
    syllabus = ROLE_SYLLABUS.get(
        role, ROLE_SYLLABUS["Software Developer"]
    )
    gap_rows = [
        row for row in (gaps or [])
        if isinstance(row, dict)
    ]

    deliverables = [
        "Write notes and solve practice questions.",
        "Complete exercises and review mistakes.",
        "Build small practical exercises.",
        "Complete hands-on tasks and review progress.",
        "Build a role-related mini-project and document it.",
    ]

    tasks = []

    for week, (module, topics) in enumerate(syllabus):
        module_text = (module + " " + " ".join(topics)).lower()

        related = next(
            (
                row for row in gap_rows
                if str(row.get("skill", "")).lower() in module_text
            ),
            None
        )

        if related is None and gap_rows:
            related = max(
                gap_rows,
                key=lambda row: float(row.get("gap", 0) or 0)
            )

        gap_size = (
            float(related.get("gap", 0) or 0)
            if related else 0
        )

        tasks.append({
            "title": f"Week {week}: {module}",
            "description": (
                "Syllabus topics:\n"
                + "\n".join(f"- {topic}" for topic in topics)
                + f"\n\nWeekly deliverable: {deliverables[week]}"
            ),
            "skill": related.get("skill", module) if related else module,
            "week": week,
            "priority": related.get("priority", "Medium") if related else "Medium",
            "hours": 4 if gap_size >= 30 else 3 if gap_size >= 10 else 2,
        })

    return tasks


def save_role_roadmap(db, student_id, assessment_id, role, gaps):
    db.execute(
        "DELETE FROM recommendations WHERE student_id=? AND kind='roadmap'",
        (student_id,)
    )

    for task in build_role_roadmap(role, gaps):
        db.execute("""
            INSERT INTO recommendations
            (student_id, assessment_id, kind, title, description,
             skill_name, week_number, priority, estimated_hours, completed)
            VALUES (?, ?, 'roadmap', ?, ?, ?, ?, ?, ?, 0)
        """, (
            student_id,
            assessment_id,
            task["title"],
            task["description"],
            task["skill"],
            task["week"],
            task["priority"],
            task["hours"]
        ))


def ensure_role_roadmap(db, student):
    latest = db.execute("""
        SELECT * FROM assessments
        WHERE student_id=?
        ORDER BY created_at DESC, id DESC
        LIMIT 1
    """, (student["id"],)).fetchone()

    if not latest:
        return db.execute("""
            SELECT * FROM recommendations
            WHERE student_id=? AND kind='roadmap'
            ORDER BY week_number, id
        """, (student["id"],)).fetchall()

    tasks = db.execute("""
        SELECT * FROM recommendations
        WHERE student_id=? AND kind='roadmap'
        ORDER BY week_number, id
    """, (student["id"],)).fetchall()

    titles = [str(task["title"]) for task in tasks]

    needs_refresh = (
        not tasks
        or not any(title.startswith("Week 0:") for title in titles)
        or not any(title.startswith("Week 1:") for title in titles)
    )

    if needs_refresh:
        try:
            gaps = json.loads(latest["gaps_json"] or "[]")
        except (TypeError, json.JSONDecodeError):
            gaps = []

        save_role_roadmap(
            db, student["id"], latest["id"],
            latest["target_role"], gaps
        )
        db.commit()

        tasks = db.execute("""
            SELECT * FROM recommendations
            WHERE student_id=? AND kind='roadmap'
            ORDER BY week_number, id
        """, (student["id"],)).fetchall()

    return tasks


# ---------------------------------------------------------
# DATABASE AND AUTHENTICATION HELPERS
# ---------------------------------------------------------

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def pathlib_schema():
    schema_path = os.path.join(BASE_DIR, "database", "schema.sql")
    with open(schema_path, encoding="utf-8") as schema_file:
        return schema_file.read()


def init_db():
    os.makedirs(os.path.dirname(DATABASE), exist_ok=True)

    conn = sqlite3.connect(DATABASE)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(pathlib_schema())

    conn.execute("""
        CREATE TABLE IF NOT EXISTS quiz_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            target_role TEXT NOT NULL,
            selected_skills_json TEXT NOT NULL,
            answers_json TEXT NOT NULL,
            results_json TEXT NOT NULL,
            score INTEGER NOT NULL,
            total_questions INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (student_id)
                REFERENCES students(id) ON DELETE CASCADE
        )
    """)

    for role, requirements in ROLE_REQUIREMENTS.items():
        conn.execute(
            "INSERT OR IGNORE INTO job_roles(name, description) VALUES (?, ?)",
            (role, f"Configurable skill requirements for {role}.")
        )

        role_row = conn.execute(
            "SELECT id FROM job_roles WHERE name=?",
            (role,)
        ).fetchone()

        if role_row:
            role_id = role_row[0]

            for skill, threshold in requirements.items():
                conn.execute("""
                    INSERT OR IGNORE INTO job_requirements
                    (role_id, skill_name, required_score)
                    VALUES (?, ?, ?)
                """, (role_id, skill, threshold))

    admin_email = os.environ.get(
        "ADMIN_EMAIL", "maya@example.com"
    ).strip().lower()

    admin_password = os.environ.get(
        "ADMIN_PASSWORD", "maya9800"
    )

    conn.execute("""
        INSERT OR IGNORE INTO admins(email, password_hash, created_at)
        VALUES (?, ?, ?)
    """, (
        admin_email,
        generate_password_hash(admin_password),
        datetime.now(timezone.utc).isoformat()
    ))

    conn.commit()
    conn.close()



def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        student = current_student()

        # Reject sessions whose student record no longer exists.
        if student is None:
            session.pop("student_id", None)
            session.pop("student_name", None)
            session.pop("pending_quiz", None)

            flash(
                "Your session is invalid or expired. Please sign in again.",
                "info"
            )
            return redirect(url_for("login"))

        return fn(*args, **kwargs)

    return wrapper



def current_student():
    student_id = session.get("student_id")

    if not student_id:
        return None

    return get_db().execute(
        "SELECT * FROM students WHERE id=?",
        (student_id,)
    ).fetchone()


def get_requirements(role):
    return ROLE_REQUIREMENTS.get(
        role, ROLE_REQUIREMENTS["Software Developer"]
    )


def get_latest_scores(student_id):
    assessment = get_db().execute("""
        SELECT * FROM assessments
        WHERE student_id=?
        ORDER BY created_at DESC, id DESC
        LIMIT 1
    """, (student_id,)).fetchone()

    if not assessment:
        return {}, None

    return json.loads(assessment["scores_json"]), assessment
@app.route("/")
def index():
    return render_template("index.html", roles=list(ROLE_REQUIREMENTS.keys()))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        college = request.form.get("college", "").strip()
        branch = request.form.get("branch", "").strip()
        year = request.form.get("academic_year", "").strip()
        graduation_year = request.form.get("graduation_year", "").strip()
        role = request.form.get("target_role", "Software Developer")

        if not name or not email or len(password) < 8:
            flash(
                "Enter your name, a valid email, and a password "
                "of at least 8 characters.",
                "error"
            )
            return render_template(
                "register.html", roles=list(ROLE_REQUIREMENTS.keys())
            )

        if role not in ROLE_REQUIREMENTS:
            role = "Software Developer"

        try:
            cur = get_db().execute("""
                INSERT INTO students
                (full_name, email, password_hash, college, branch,
                 academic_year, graduation_year, target_role, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                name, email, generate_password_hash(password),
                college, branch, year, graduation_year, role,
                datetime.now(timezone.utc).isoformat()
            ))

            get_db().commit()
            session["student_id"] = cur.lastrowid
            session["student_name"] = name

            flash(
                "Your profile is ready. Add your skill scores to begin.",
                "success"
            )
            return redirect(url_for("assessment"))

        except sqlite3.IntegrityError:
            flash(
                "An account with that email already exists. Please sign in.",
                "error"
            )

    return render_template(
        "register.html", roles=list(ROLE_REQUIREMENTS.keys())
    )


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        student = get_db().execute(
            "SELECT * FROM students WHERE email=?",
            (email,)
        ).fetchone()

        if student and check_password_hash(
            student["password_hash"], password
        ):
            session.clear()
            session["student_id"] = student["id"]
            session["student_name"] = student["full_name"]

            flash("Welcome back!", "success")
            return redirect(url_for("dashboard"))

        flash("Email or password is incorrect.", "error")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been signed out.", "info")
    return redirect(url_for("index"))


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    db = get_db()
    student = current_student()

    if request.method == "POST":
        role = request.form.get("target_role", "Software Developer")

        if role not in ROLE_REQUIREMENTS:
            role = "Software Developer"

        full_name = request.form.get("full_name", "").strip()

        db.execute("""
            UPDATE students
            SET full_name=?, college=?, branch=?, academic_year=?,
                graduation_year=?, target_role=?
            WHERE id=?
        """, (
            full_name,
            request.form.get("college", "").strip(),
            request.form.get("branch", "").strip(),
            request.form.get("academic_year", "").strip(),
            request.form.get("graduation_year", "").strip(),
            role,
            student["id"]
        ))

        db.commit()
        session["student_name"] = full_name

        flash("Profile updated.", "success")
        return redirect(url_for("profile"))

    return render_template(
        "profile.html",
        student=student,
        roles=list(ROLE_REQUIREMENTS.keys())
    )


@app.route("/assessment", methods=["GET", "POST"])
@login_required
def assessment():
    student = current_student()
    role = student["target_role"]
    requirements = get_requirements(role)
    db = get_db()

    if request.method == "POST":
        scores = {}
        errors = []

        for skill in requirements:
            try:
                value = float(request.form.get("score_" + skill, ""))

                if not 0 <= value <= 100:
                    raise ValueError

                scores[skill] = round(value, 1)

            except (ValueError, TypeError):
                errors.append(
                    f"{skill} must be a number between 0 and 100."
                )

        if errors:
            for error in errors:
                flash(error, "error")

            return render_template(
                "assessment.html",
                student=student,
                requirements=requirements,
                scores=scores
            )

        gaps = analyze_gaps(scores, requirements)

        projects_count = db.execute(
            "SELECT COUNT(*) FROM projects WHERE student_id=?",
            (student["id"],)
        ).fetchone()[0]

        cert_count = db.execute(
            "SELECT COUNT(*) FROM certifications WHERE student_id=?",
            (student["id"],)
        ).fetchone()[0]

        readiness = calculate_readiness(
            scores,
            projects_count=projects_count,
            certifications_count=cert_count,
            profile=dict(student)
        )

        cur = db.execute("""
            INSERT INTO assessments
            (student_id, target_role, scores_json, gaps_json,
             readiness_score, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            student["id"],
            role,
            json.dumps(scores),
            json.dumps(gaps),
            readiness["score"],
            datetime.now(timezone.utc).isoformat()
        ))

        assessment_id = cur.lastrowid

        for row in gaps:
            db.execute("""
                INSERT INTO skills
                (student_id, assessment_id, skill_name, proficiency,
                 required_score, gap, priority)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                student["id"],
                assessment_id,
                row["skill"],
                row["current"],
                row["required"],
                row["gap"],
                row["priority"]
            ))

        # Generate the role-specific Week 0–Week 4 roadmap.
        save_role_roadmap(
            db, student["id"], assessment_id, role, gaps
        )

        db.commit()
        return redirect(url_for("dashboard"))

    scores, _ = get_latest_scores(student["id"])

    return render_template(
        "assessment.html",
        student=student,
        requirements=requirements,
        scores=scores
    )


@app.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    student = current_student()
    scores, assessment_row = get_latest_scores(student["id"])

    if assessment_row:
        gaps = json.loads(assessment_row["gaps_json"])

        readiness = calculate_readiness(
            scores,
            projects_count=db.execute(
                "SELECT COUNT(*) FROM projects WHERE student_id=?",
                (student["id"],)
            ).fetchone()[0],
            certifications_count=db.execute(
                "SELECT COUNT(*) FROM certifications WHERE student_id=?",
                (student["id"],)
            ).fetchone()[0],
            profile=dict(student)
        )

        tasks = ensure_role_roadmap(db, student)

        projects_list = recommend_projects(
            student["target_role"], gaps
        )

        history = db.execute("""
            SELECT created_at, readiness_score
            FROM assessments
            WHERE student_id=?
            ORDER BY created_at DESC
            LIMIT 6
        """, (student["id"],)).fetchall()

    else:
        gaps = []
        tasks = []
        projects_list = []
        history = []

        readiness = {
            "score": 0,
            "components": {},
            "note": "Complete an assessment to calculate your score."
        }

    completed = sum(1 for task in tasks if task["completed"])
    progress_pct = round(completed / len(tasks) * 100) if tasks else 0

    return render_template(
        "dashboard.html",
        student=student,
        scores=scores,
        gaps=gaps,
        readiness=readiness,
        tasks=tasks,
        projects=projects_list,
        history=list(reversed(history)),
        progress_pct=progress_pct,
        requirements=get_requirements(student["target_role"])
    )


@app.route("/roadmap")
@login_required
def roadmap():
    db = get_db()
    student = current_student()

    # Regenerates an old or missing roadmap when needed.
    tasks = ensure_role_roadmap(db, student)

    total = len(tasks)
    completed = sum(1 for task in tasks if task["completed"])

    return render_template(
        "roadmap.html",
        student=student,
        tasks=tasks,
        progress_pct=round(completed / total * 100) if total else 0,
        syllabus=ROLE_SYLLABUS.get(
            student["target_role"],
            ROLE_SYLLABUS["Software Developer"]
        )
    )


@app.route("/admin/reset-database", methods=["POST"])
def admin_reset_database():
    if not session.get("admin_id"):
        flash("Please sign in as an administrator.", "error")
        return redirect(url_for("admin_login"))

    if request.form.get("confirm_reset", "").strip() != "RESET":
        flash("Type RESET to confirm the database reset.", "error")
        return redirect(url_for("admin_dashboard"))

    db = get_db()

    tables_to_clear = [
        "progress",
        "quiz_attempts",
        "skills",
        "recommendations",
        "projects",
        "certifications",
        "assessments",
        "students",
    ]

    try:
        existing_tables = {
            row["name"]
            for row in db.execute("""
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
            """).fetchall()
        }

        # Clear dependent records before student records.
        for table in tables_to_clear:
            if table in existing_tables:
                db.execute(f'DELETE FROM "{table}"')

        # Reset generated IDs for cleared tables when applicable.
        if "sqlite_sequence" in existing_tables:
            for table in tables_to_clear:
                if table in existing_tables:
                    db.execute(
                        "DELETE FROM sqlite_sequence WHERE name = ?",
                        (table,)
                    )

        db.commit()

        # Log the admin out of any student session state.
        session.pop("student_id", None)
        session.pop("student_name", None)
        session.pop("pending_quiz", None)

        flash(
            "Reset successful. Student and testing records were deleted. "
            "The admin account and role configuration were preserved.",
            "success"
        )

    except sqlite3.Error:
        db.rollback()
        app.logger.exception("Database reset failed")
        flash("Reset failed. Check the Flask console for details.", "error")

    return redirect(url_for("admin_dashboard"))


@app.route("/tasks/<int:task_id>/toggle", methods=["POST"])
@login_required
def toggle_task(task_id):
    db = get_db()

    task = db.execute("""
        SELECT *
        FROM recommendations
        WHERE id=? AND student_id=? AND kind='roadmap'
    """, (
        task_id,
        session["student_id"]
    )).fetchone()

    if not task:
        flash("Task not found.", "error")
        return redirect(url_for("roadmap"))

    new_value = 0 if task["completed"] else 1

    db.execute(
        "UPDATE recommendations SET completed=? WHERE id=?",
        (new_value, task_id)
    )

    # FIX: The database column is skill_name, not skill.
    # Use the title as a safe fallback.
    task_columns = set(task.keys())

    skill_name = (
        task["skill_name"]
        if "skill_name" in task_columns and task["skill_name"]
        else task["title"]
    )

    db.execute("""
        INSERT INTO progress
        (student_id, skill_name, old_score, new_score, note, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        session["student_id"],
        skill_name,
        None,
        None,
        "Roadmap task " + (
            "completed" if new_value else "reopened"
        ) + ": " + task["title"],
        datetime.now(timezone.utc).isoformat()
    ))

    db.commit()

    flash("Task status updated.", "success")
    return redirect(request.referrer or url_for("roadmap"))


@app.route("/projects", methods=["GET", "POST"])
@login_required
def projects():
    db = get_db()
    student = current_student()

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        skills = request.form.get("skills", "").strip()

        if title:
            db.execute("""
                INSERT INTO projects
                (student_id, title, description, skills, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (
                student["id"],
                title,
                description,
                skills,
                datetime.now(timezone.utc).isoformat()
            ))

            db.commit()
            flash("Project added to your profile.", "success")
            return redirect(url_for("projects"))

        flash("Project title is required.", "error")

    saved = db.execute("""
        SELECT *
        FROM projects
        WHERE student_id=?
        ORDER BY id DESC
    """, (student["id"],)).fetchall()

    return render_template(
        "projects.html", student=student, saved=saved
    )


@app.route("/certifications", methods=["GET", "POST"])
@login_required
def certifications():
    db = get_db()
    student = current_student()

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        issuer = request.form.get("issuer", "").strip()

        if title:
            db.execute("""
                INSERT INTO certifications
                (student_id, title, issuer, created_at)
                VALUES (?, ?, ?, ?)
            """, (
                student["id"],
                title,
                issuer,
                datetime.now(timezone.utc).isoformat()
            ))

            db.commit()
            flash("Certification added.", "success")
            return redirect(url_for("certifications"))

        flash("Certification title is required.", "error")

    saved = db.execute("""
        SELECT *
        FROM certifications
        WHERE student_id=?
        ORDER BY id DESC
    """, (student["id"],)).fetchall()

    return render_template(
        "certifications.html", student=student, saved=saved
    )


@app.route("/progress")
@login_required
def progress():
    db = get_db()
    student = current_student()

    assessments = db.execute("""
        SELECT *
        FROM assessments
        WHERE student_id=?
        ORDER BY created_at ASC
    """, (student["id"],)).fetchall()

    history = []
    previous = {}

    for assessment_row in assessments:
        scores = json.loads(assessment_row["scores_json"])

        deltas = {
            key: round(value - previous[key], 1)
            for key, value in scores.items()
            if key in previous
        }

        history.append({
            "date": assessment_row["created_at"][:10],
            "role": assessment_row["target_role"],
            "score": assessment_row["readiness_score"],
            "scores": scores,
            "deltas": deltas
        })

        previous = scores

    events = db.execute("""
        SELECT *
        FROM progress
        WHERE student_id=?
        ORDER BY created_at DESC
        LIMIT 20
    """, (student["id"],)).fetchall()

    return render_template(
        "progress.html",
        student=student,
        history=history,
        events=events
    )


@app.route("/api/requirements/<path:role>")
@login_required
def api_requirements(role):
    if role not in ROLE_REQUIREMENTS:
        return jsonify({"error": "Unknown role"}), 404

    return jsonify(ROLE_REQUIREMENTS[role])


@app.route("/course-analyzer", methods=["GET", "POST"])
@login_required
def course_analyzer():
    student = current_student()
    roles = list(ROLE_REQUIREMENTS.keys())
    selected_role = student["target_role"]
    selected_skills = DEFAULT_SKILLS[selected_role]

    if request.method == "POST":
        selected_role = request.form.get("target_role", "")

        if selected_role not in ROLE_REQUIREMENTS:
            flash("Choose a valid target role.", "error")
            return render_template(
                "course_analyzer.html",
                student=student,
                roles=roles,
                skill_options=DEFAULT_SKILLS,
                selected_role=student["target_role"],
                selected_skills=[]
            )

        allowed = DEFAULT_SKILLS[selected_role]

        selected_skills = [
            skill
            for skill in request.form.getlist("skills")
            if skill in allowed and skill in QUIZ_BANK
        ]

        if not selected_skills:
            flash(
                "Select at least one skill to generate your assessment.",
                "error"
            )
            return render_template(
                "course_analyzer.html",
                student=student,
                roles=roles,
                skill_options=DEFAULT_SKILLS,
                selected_role=selected_role,
                selected_skills=[]
            )

        session["pending_quiz"] = {
            "role": selected_role,
            "skills": selected_skills
        }

        return redirect(url_for("take_quiz"))

    return render_template(
        "course_analyzer.html",
        student=student,
        roles=roles,
        skill_options=DEFAULT_SKILLS,
        selected_role=selected_role,
        selected_skills=selected_skills
    )


@app.route("/course-analyzer/test", methods=["GET", "POST"])
@login_required
def take_quiz():
    db = get_db()
    pending = session.get("pending_quiz")

    if not pending or pending.get("role") not in ROLE_REQUIREMENTS:
        flash("Choose a target role and skills first.", "info")
        return redirect(url_for("course_analyzer"))

    valid_skills = [
        skill
        for skill in pending.get("skills", [])
        if skill in DEFAULT_SKILLS[pending["role"]]
        and skill in QUIZ_BANK
    ]

    if not valid_skills:
        session.pop("pending_quiz", None)
        flash(
            "No valid quiz skills were selected. Please choose again.",
            "error"
        )
        return redirect(url_for("course_analyzer"))

    questions = []

    for skill in valid_skills:
        for index, question in enumerate(QUIZ_BANK[skill]):
            questions.append({
                "id": f"{skill}__{index}",
                "skill": skill,
                "q": question["q"],
                "options": question["options"]
            })

    if request.method == "POST":
        per_skill = {
            skill: {"correct": 0, "total": 0, "missed": []}
            for skill in valid_skills
        }

        answer_summary = {}

        for question in questions:
            skill, index_text = question["id"].rsplit("__", 1)
            source = QUIZ_BANK[skill][int(index_text)]

            raw = request.form.get("answer_" + question["id"], "")

            try:
                chosen = int(raw)
            except (TypeError, ValueError):
                chosen = -1

            correct = chosen == source["answer"]
            per_skill[skill]["total"] += 1

            if correct:
                per_skill[skill]["correct"] += 1
            else:
                per_skill[skill]["missed"].append({
                    "question": source["q"],
                    "correct_answer": source["options"][source["answer"]],
                    "explanation": source["explanation"]
                })

            answer_summary[question["id"]] = {
                "chosen": chosen,
                "correct": correct
            }

        skill_results = []

        for skill, item in per_skill.items():
            skill_score = (
                round(item["correct"] / item["total"] * 100)
                if item["total"] else 0
            )

            skill_results.append({
                "skill": skill,
                "correct": item["correct"],
                "total": item["total"],
                "score": skill_score,
                "level": (
                    "Strong" if skill_score >= 80
                    else "Developing" if skill_score >= 50
                    else "Needs focus"
                ),
                "missed": item["missed"]
            })

        total = sum(item["total"] for item in skill_results)
        correct_total = sum(item["correct"] for item in skill_results)

        overall_score = (
            round(correct_total / total * 100) if total else 0
        )

        result = {
            "overall_score": overall_score,
            "correct": correct_total,
            "total": total,
            "skills": skill_results,
            "recommendations": [
                (
                    f"Practice {item['skill']} first: "
                    f"assessment score {item['score']}%."
                )
                for item in sorted(
                    skill_results, key=lambda item: item["score"]
                )
                if item["score"] < 80
            ]
        }

        try:
            db.execute("""
                INSERT INTO quiz_attempts
                (student_id, target_role, selected_skills_json,
                 answers_json, results_json, score,
                 total_questions, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                session["student_id"],
                pending["role"],
                json.dumps(valid_skills),
                json.dumps(answer_summary),
                json.dumps(result),
                overall_score,
                total,
                datetime.now(timezone.utc).isoformat()
            ))

            db.commit()

        except sqlite3.Error:
            db.rollback()
            app.logger.exception("Could not save quiz attempt")

            flash(
                "Your quiz was graded, but the result could not be saved. "
                "Check the server log.",
                "error"
            )

            return render_template(
                "course_results.html",
                student=current_student(),
                role=pending["role"],
                result=result
            ), 500

        session.pop("pending_quiz", None)

        return render_template(
            "course_results.html",
            student=current_student(),
            role=pending["role"],
            result=result
        )

    return render_template(
        "take_quiz.html",
        student=current_student(),
        role=pending["role"],
        skills=valid_skills,
        questions=questions
    )
# ---------------------------------------------------------
# ADMIN LOGIN
# ---------------------------------------------------------

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        admin = get_db().execute(
            "SELECT * FROM admins WHERE email=?",
            (email,)
        ).fetchone()

        if admin and check_password_hash(
            admin["password_hash"], password
        ):
            session.clear()
            session["admin_id"] = admin["id"]
            session["admin_email"] = admin["email"]

            return redirect(url_for("admin_dashboard"))

        flash("Admin email or password is incorrect.", "error")

    return render_template("admin_login.html")


# ---------------------------------------------------------
# ADMIN DASHBOARD
# ---------------------------------------------------------

@app.route("/admin")
def admin_dashboard():
    if not session.get("admin_id"):
        return redirect(url_for("admin_login"))

    db = get_db()

    stats = {
        "students": db.execute(
            "SELECT COUNT(*) FROM students"
        ).fetchone()[0],

        "assessments": db.execute(
            "SELECT COUNT(*) FROM assessments"
        ).fetchone()[0],

        "quiz_attempts": db.execute(
            "SELECT COUNT(*) FROM quiz_attempts"
        ).fetchone()[0],

        "projects": db.execute(
            "SELECT COUNT(*) FROM projects"
        ).fetchone()[0],
    }

    students = db.execute("""
        SELECT
            s.id,
            s.full_name,
            s.email,
            s.target_role,
            s.created_at,

            (
                SELECT COUNT(*)
                FROM assessments a
                WHERE a.student_id=s.id
            ) AS assessment_count,

            (
                SELECT COUNT(*)
                FROM quiz_attempts q
                WHERE q.student_id=s.id
            ) AS quiz_count,

            (
                SELECT score
                FROM quiz_attempts q
                WHERE q.student_id=s.id
                ORDER BY q.id DESC
                LIMIT 1
            ) AS latest_quiz_score

        FROM students s
        ORDER BY s.created_at DESC
        LIMIT 100
    """).fetchall()

    attempts = db.execute("""
        SELECT
            q.id,
            q.target_role,
            q.score,
            q.total_questions,
            q.created_at,
            s.full_name,
            s.email

        FROM quiz_attempts q
        JOIN students s ON s.id=q.student_id
        ORDER BY q.id DESC
        LIMIT 50
    """).fetchall()

    return render_template(
        "admin_dashboard.html",
        stats=stats,
        students=students,
        attempts=attempts,
        admin_email=session.get("admin_email")
    )


# ---------------------------------------------------------
# ADMIN: DELETE A STUDENT AND THEIR RELATED DATA
# ---------------------------------------------------------

@app.route(
    "/admin/students/<int:student_id>/delete",
    methods=["POST"]
)
def admin_delete_student(student_id):
    if not session.get("admin_id"):
        flash("Please sign in as an administrator.", "error")
        return redirect(url_for("admin_login"))

    db = get_db()

    student = db.execute(
        "SELECT id, full_name FROM students WHERE id=?",
        (student_id,)
    ).fetchone()

    if not student:
        flash("Student not found.", "error")
        return redirect(url_for("admin_dashboard"))

    try:
        # Delete child records before deleting the student.
        db.execute(
            "DELETE FROM quiz_attempts WHERE student_id=?",
            (student_id,)
        )

        db.execute(
            "DELETE FROM progress WHERE student_id=?",
            (student_id,)
        )

        db.execute(
            "DELETE FROM recommendations WHERE student_id=?",
            (student_id,)
        )

        db.execute(
            "DELETE FROM skills WHERE student_id=?",
            (student_id,)
        )

        db.execute(
            "DELETE FROM projects WHERE student_id=?",
            (student_id,)
        )

        db.execute(
            "DELETE FROM certifications WHERE student_id=?",
            (student_id,)
        )

        db.execute(
            "DELETE FROM assessments WHERE student_id=?",
            (student_id,)
        )

        db.execute(
            "DELETE FROM students WHERE id=?",
            (student_id,)
        )

        db.commit()

        flash(
            f"Deleted student data for {student['full_name']}.",
            "success"
        )

    except sqlite3.Error:
        db.rollback()

        app.logger.exception(
            "Could not delete student %s", student_id
        )

        flash(
            "Could not delete student data. Check the server log "
            "and database schema.",
            "error"
        )

    return redirect(url_for("admin_dashboard"))


@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))


# ---------------------------------------------------------
# DEMO LOGIN
# ---------------------------------------------------------

@app.route("/demo-login")
def demo_login():
    db = get_db()

    student = db.execute(
        "SELECT * FROM students WHERE email=?",
        ("demo@example.com",)
    ).fetchone()

    if not student:
        cur = db.execute("""
            INSERT INTO students
            (full_name, email, password_hash, college, branch,
             academic_year, graduation_year, target_role, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "Demo Student",
            "demo@example.com",
            generate_password_hash("DemoPass123!"),
            "Sample College",
            "Computer Science",
            "3",
            "2027",
            "Software Developer",
            datetime.now(timezone.utc).isoformat()
        ))

        student_id = cur.lastrowid

        scores = {
            "Python": 75,
            "Java": 60,
            "DSA": 35,
            "SQL": 50,
            "Aptitude": 68
        }

        gaps = analyze_gaps(
            scores,
            ROLE_REQUIREMENTS["Software Developer"]
        )

        readiness = calculate_readiness(
            scores,
            projects_count=1,
            certifications_count=1,
            profile={
                "full_name": "Demo Student",
                "college": "Sample College",
                "branch": "Computer Science",
                "graduation_year": "2027"
            }
        )

        cur = db.execute("""
            INSERT INTO assessments
            (student_id, target_role, scores_json, gaps_json,
             readiness_score, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            student_id,
            "Software Developer",
            json.dumps(scores),
            json.dumps(gaps),
            readiness["score"],
            datetime.now(timezone.utc).isoformat()
        ))

        assessment_id = cur.lastrowid

        for row in gaps:
            db.execute("""
                INSERT INTO skills
                (student_id, assessment_id, skill_name, proficiency,
                 required_score, gap, priority)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                student_id,
                assessment_id,
                row["skill"],
                row["current"],
                row["required"],
                row["gap"],
                row["priority"]
            ))

        db.execute("""
            INSERT INTO projects
            (student_id, title, description, skills, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (
            student_id,
            "Student Management System",
            "A CRUD application to practice core development.",
            "Python, SQL",
            datetime.now(timezone.utc).isoformat()
        ))

        db.execute("""
            INSERT INTO certifications
            (student_id, title, issuer, created_at)
            VALUES (?, ?, ?, ?)
        """, (
            student_id,
            "Python Fundamentals",
            "Sample Learning Platform",
            datetime.now(timezone.utc).isoformat()
        ))

        save_role_roadmap(
            db,
            student_id,
            assessment_id,
            "Software Developer",
            gaps
        )

        db.commit()

    else:
        student_id = student["id"]

    demo_student = db.execute(
        "SELECT full_name FROM students WHERE id=?",
        (student_id,)
    ).fetchone()

    session["student_id"] = student_id
    session["student_name"] = (
        demo_student["full_name"]
        if demo_student else "Demo Student"
    )

    flash(
        "You are viewing the sample demonstration account.",
        "info"
    )

    return redirect(url_for("dashboard"))


# ---------------------------------------------------------
# APPLICATION STARTUP
# ---------------------------------------------------------

if __name__ == "__main__":
    init_db()

    app.run(
        debug=os.environ.get("FLASK_DEBUG", "0") == "1"
    )

# Initialize the database when the app starts on Render/Gunicorn.
with app.app_context():
    init_db()



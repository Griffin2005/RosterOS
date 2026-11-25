"""Fictional but realistic sample dataset.

32 employees, 4 pods (each with a lead), 22 brands: 18 run by one dedicated
employee (82%), 2 with two people (separate processes / shared process) and 2
with three people (overlapping CS plus separate ACC / NDR).

Working rules and minimum coverage are NOT defined here as database rows: they
live in the (mock) Google Sheet `RULE_SHEET_ROWS` and are imported through the
same path a real Sheet would use.
"""

PROCESSES = [
    ("CS", "Customer Support"),
    ("ACC", "Abandoned Cart Conversion"),
    ("NDR", "Non-Delivery Report management"),
    ("RET", "Retention"),
    ("ESC", "Escalations"),
]

PODS = [
    # id, name, lead employee code
    ("pod-north", "Pod North", "E01"),
    ("pod-south", "Pod South", "E02"),
    ("pod-east", "Pod East", "E03"),
    ("pod-west", "Pod West", "E04"),
]

# code, name, pod, holiday calendar, preferred off weekdays (0=Mon..6=Sun)
EMPLOYEES = [
    ("E01", "Kavya Sharma", "pod-north", None, [6]),
    ("E02", "Rohan Pillai", "pod-south", None, [6]),
    ("E03", "Ananya Das", "pod-east", "IN-WB", [6]),
    ("E04", "Vikram Joshi", "pod-west", "IN-MH", [6]),
    # North
    ("E05", "Rahul Menon", "pod-north", None, []),
    ("E06", "Neha Kapoor", "pod-north", None, [6]),
    ("E07", "Aman Verma", "pod-north", None, [5]),
    ("E08", "Simran Kaur", "pod-north", None, [6]),
    ("E09", "Karan Malhotra", "pod-north", None, [0]),
    ("E10", "Ishita Bansal", "pod-north", None, [6]),
    ("E11", "Tenzin Dorje", "pod-north", None, [6]),
    # South
    ("E12", "Meera Iyer", "pod-south", None, [5]),
    ("E13", "Arjun Rao", "pod-south", None, [6]),
    ("E14", "Divya Nair", "pod-south", None, [2]),
    ("E15", "Lakshmi Menon", "pod-south", None, [6]),
    ("E16", "Sana Khan", "pod-south", None, [4]),
    ("E17", "Imran Qureshi", "pod-south", None, [1]),
    ("E18", "Pooja Reddy", "pod-south", None, [6]),
    # East
    ("E19", "Sourav Ghosh", "pod-east", "IN-WB", [6]),
    ("E20", "Riya Sen", "pod-east", "IN-WB", [3]),
    ("E21", "Arnab Roy", "pod-east", "IN-WB", [0]),
    ("E22", "Moumita Paul", "pod-east", "IN-WB", [6]),
    ("E23", "Tanvi Shah", "pod-east", "IN-WB", [2]),
    ("E24", "Nikhil Bose", "pod-east", "IN-WB", [4]),
    ("E25", "Priya Chatterjee", "pod-east", "IN-WB", [6]),
    # West
    ("E26", "Hetal Patel", "pod-west", "IN-MH", [6]),
    ("E27", "Kabir Mehta", "pod-west", "IN-MH", [1]),
    ("E28", "Sneha Kulkarni", "pod-west", "IN-MH", [3]),
    ("E29", "Aditya Deshmukh", "pod-west", "IN-MH", [6]),
    ("E30", "Zoya Sheikh", "pod-west", "IN-MH", [0]),
    ("E31", "Manav Trivedi", "pod-west", "IN-MH", [6]),
    ("E32", "Fiona D'Souza", "pod-west", "IN-MH", [4]),
]

# brand, pod, tier
BRANDS = [
    ("Himalayan Brew", "pod-north", "B"),
    ("Pashmina House", "pod-north", "C"),
    ("Doon Organics", "pod-north", "B"),
    ("Kashmir Crafts", "pod-north", "C"),
    ("Peak Performance", "pod-north", "A"),
    ("Ladakh Trails", "pod-north", "C"),
    ("Kesar Kitchen", "pod-south", "B"),
    ("Loom & Lark", "pod-south", "C"),
    ("Nimbu Naturals", "pod-south", "B"),
    ("Coconut Grove", "pod-south", "C"),
    ("Urban Tandoor", "pod-south", "A"),
    ("Bengal Loom", "pod-east", "C"),
    ("Darjeeling Leaf", "pod-east", "B"),
    ("Mishti Box", "pod-east", "B"),
    ("Jute & Co", "pod-east", "C"),
    ("Bloom Basket", "pod-east", "A"),
    ("Gujarat Spice Co", "pod-west", "C"),
    ("Marine Drive Apparel", "pod-west", "B"),
    ("Konkan Coast", "pod-west", "B"),
    ("Pune Pedal", "pod-west", "C"),
    ("Rann Rugs", "pod-west", "B"),
    ("Goa Breeze", "pod-west", "B"),
]

# The Google Sheet "Rules & Coverage" -> tab "ServiceLines"
RULE_SHEET_HEADER = ["brand", "process", "calendar", "weekdays", "min_heads", "weekday_min", "shift"]
RULE_SHEET_ROWS = [
    ["Himalayan Brew", "CS", "ALL_DAYS", "", "1", "", "09:30-18:30"],
    ["Himalayan Brew", "RET", "NO_SUN_PH", "", "1", "", "10:00-19:00"],
    ["Pashmina House", "CS", "NO_SUN_PH", "", "1", "", "09:30-18:30"],
    ["Pashmina House", "NDR", "NO_SUN_PH", "", "1", "", "10:00-19:00"],
    ["Doon Organics", "CS", "NO_PH", "", "1", "", "09:30-18:30"],
    ["Doon Organics", "ACC", "NO_SUN_PH", "", "1", "", "10:00-19:00"],
    ["Kashmir Crafts", "CS", "NO_SUN_PH", "", "1", "", "09:30-18:30"],
    ["Peak Performance", "CS", "ALL_DAYS", "", "1", "", "09:00-18:00"],
    ["Peak Performance", "ACC", "NO_SUN_PH", "", "1", "", "10:00-19:00"],
    ["Peak Performance", "RET", "NO_SUN_PH", "", "1", "", "10:00-19:00"],
    ["Ladakh Trails", "CS", "NO_SUN_PH", "", "1", "", "09:30-18:30"],
    ["Ladakh Trails", "ACC", "NO_SUN_PH", "", "1", "", "10:00-19:00"],
    ["Kesar Kitchen", "CS", "ALL_DAYS", "", "1", "", "09:00-18:00"],
    ["Kesar Kitchen", "ACC", "NO_SUN_PH", "", "1", "", "10:00-19:00"],
    ["Kesar Kitchen", "NDR", "NO_PH", "", "1", "", "10:00-19:00"],
    ["Loom & Lark", "CS", "NO_SUN_PH", "", "1", "", "09:30-18:30"],
    ["Loom & Lark", "RET", "NO_SUN_PH", "", "1", "", "10:00-19:00"],
    ["Nimbu Naturals", "CS", "NO_PH", "", "1", "", "09:30-18:30"],
    ["Nimbu Naturals", "ACC", "NO_SUN_PH", "", "1", "", "10:00-19:00"],
    ["Coconut Grove", "CS", "NO_SUN_PH", "", "1", "", "09:30-18:30"],
    ["Coconut Grove", "NDR", "NO_SUN_PH", "", "1", "", "10:00-19:00"],
    ["Urban Tandoor", "CS", "ALL_DAYS", "", "1", "Sat:2", "09:00-18:00"],
    ["Urban Tandoor", "NDR", "NO_SUN_PH", "", "1", "", "12:00-21:00"],
    ["Bengal Loom", "CS", "NO_SUN_PH", "", "1", "", "09:30-18:30"],
    ["Bengal Loom", "ACC", "NO_SUN_PH", "", "1", "", "10:00-19:00"],
    ["Darjeeling Leaf", "CS", "ALL_DAYS", "", "1", "", "09:00-18:00"],
    ["Darjeeling Leaf", "RET", "NO_SUN_PH", "", "1", "", "10:00-19:00"],
    ["Mishti Box", "CS", "NO_PH", "", "1", "", "09:30-18:30"],
    ["Mishti Box", "NDR", "NO_PH", "", "1", "", "10:00-19:00"],
    ["Jute & Co", "CS", "NO_SUN_PH", "", "1", "", "09:30-18:30"],
    ["Jute & Co", "ACC", "NO_SUN_PH", "", "1", "", "10:00-19:00"],
    ["Bloom Basket", "CS", "ALL_DAYS", "", "1", "Sun:2", "09:00-18:00"],
    ["Bloom Basket", "ACC", "NO_SUN_PH", "", "1", "", "10:00-19:00"],
    ["Bloom Basket", "NDR", "NO_PH", "", "1", "", "10:00-19:00"],
    ["Gujarat Spice Co", "CS", "NO_SUN_PH", "", "1", "", "09:30-18:30"],
    ["Gujarat Spice Co", "ACC", "NO_SUN_PH", "", "1", "", "10:00-19:00"],
    ["Marine Drive Apparel", "CS", "ALL_DAYS", "", "1", "", "09:00-18:00"],
    ["Marine Drive Apparel", "ACC", "NO_SUN_PH", "", "1", "", "10:00-19:00"],
    ["Konkan Coast", "CS", "NO_PH", "", "1", "", "09:30-18:30"],
    ["Konkan Coast", "NDR", "NO_PH", "", "1", "", "10:00-19:00"],
    ["Pune Pedal", "CS", "NO_SUN_PH", "", "1", "", "09:30-18:30"],
    ["Pune Pedal", "RET", "NO_SUN_PH", "", "1", "", "10:00-19:00"],
    ["Rann Rugs", "CS", "NO_PH", "", "1", "", "09:30-18:30"],
    ["Rann Rugs", "NDR", "NO_SUN_PH", "", "1", "", "10:00-19:00"],
    ["Goa Breeze", "CS", "ALL_DAYS", "", "1", "", "09:00-18:00"],
    ["Goa Breeze", "RET", "NO_SUN_PH", "", "1", "", "10:00-19:00"],
]

# Tab "CoverageOverrides"
OVERRIDE_SHEET_HEADER = ["brand", "process", "date", "min_heads", "reason"]
OVERRIDE_SHEET_ROWS = [
    ["Urban Tandoor", "CS", "2026-12-25", "3", "Christmas sale"],
    ["Bloom Basket", "CS", "2026-12-31", "2", "New Year's Eve gifting"],
]

# employee code, brand, process, role, load %
ASSIGNMENTS = [
    # ---- North
    ("E05", "Himalayan Brew", "CS", "PRIMARY", 60), ("E05", "Himalayan Brew", "RET", "PRIMARY", 40),
    ("E06", "Pashmina House", "CS", "PRIMARY", 70), ("E06", "Pashmina House", "NDR", "PRIMARY", 30),
    ("E07", "Doon Organics", "CS", "PRIMARY", 60), ("E07", "Doon Organics", "ACC", "PRIMARY", 40),
    ("E08", "Kashmir Crafts", "CS", "PRIMARY", 70),
    ("E09", "Peak Performance", "CS", "PRIMARY", 60),
    ("E10", "Peak Performance", "ACC", "PRIMARY", 50), ("E10", "Peak Performance", "RET", "PRIMARY", 50),
    ("E11", "Ladakh Trails", "CS", "PRIMARY", 50), ("E11", "Ladakh Trails", "ACC", "PRIMARY", 50),
    # ---- South
    ("E12", "Kesar Kitchen", "CS", "PRIMARY", 50), ("E12", "Kesar Kitchen", "ACC", "PRIMARY", 25),
    ("E12", "Kesar Kitchen", "NDR", "PRIMARY", 25),
    ("E13", "Loom & Lark", "CS", "PRIMARY", 60), ("E13", "Loom & Lark", "RET", "PRIMARY", 40),
    ("E14", "Nimbu Naturals", "CS", "PRIMARY", 60), ("E14", "Nimbu Naturals", "ACC", "PRIMARY", 40),
    ("E15", "Coconut Grove", "CS", "PRIMARY", 70), ("E15", "Coconut Grove", "NDR", "PRIMARY", 30),
    ("E16", "Urban Tandoor", "CS", "PRIMARY", 60),
    ("E17", "Urban Tandoor", "CS", "PRIMARY", 60),
    ("E18", "Urban Tandoor", "NDR", "PRIMARY", 40), ("E18", "Urban Tandoor", "CS", "PRIMARY", 60),
    # ---- East
    ("E19", "Bengal Loom", "CS", "PRIMARY", 60), ("E19", "Bengal Loom", "ACC", "PRIMARY", 40),
    ("E20", "Darjeeling Leaf", "CS", "PRIMARY", 60), ("E20", "Darjeeling Leaf", "RET", "PRIMARY", 40),
    ("E21", "Mishti Box", "CS", "PRIMARY", 50), ("E21", "Mishti Box", "NDR", "PRIMARY", 50),
    ("E22", "Jute & Co", "CS", "PRIMARY", 60), ("E22", "Jute & Co", "ACC", "PRIMARY", 40),
    ("E23", "Bloom Basket", "CS", "PRIMARY", 60),
    ("E24", "Bloom Basket", "CS", "PRIMARY", 60), ("E24", "Bloom Basket", "NDR", "PRIMARY", 40),
    ("E25", "Bloom Basket", "ACC", "PRIMARY", 40), ("E25", "Bloom Basket", "NDR", "PRIMARY", 40),
    # ---- West
    ("E26", "Gujarat Spice Co", "CS", "PRIMARY", 50), ("E26", "Gujarat Spice Co", "ACC", "PRIMARY", 50),
    ("E27", "Marine Drive Apparel", "CS", "PRIMARY", 60), ("E27", "Marine Drive Apparel", "ACC", "PRIMARY", 40),
    ("E28", "Konkan Coast", "CS", "PRIMARY", 60), ("E28", "Konkan Coast", "NDR", "PRIMARY", 40),
    ("E29", "Pune Pedal", "CS", "PRIMARY", 70), ("E29", "Pune Pedal", "RET", "PRIMARY", 30),
    ("E30", "Rann Rugs", "CS", "PRIMARY", 50),
    ("E31", "Rann Rugs", "CS", "PRIMARY", 50), ("E31", "Rann Rugs", "NDR", "PRIMARY", 50),
    ("E32", "Goa Breeze", "CS", "PRIMARY", 60), ("E32", "Goa Breeze", "RET", "PRIMARY", 40),
    # ---- cross-trained backups (peers)
    ("E13", "Kesar Kitchen", "CS", "BACKUP", 50), ("E13", "Kesar Kitchen", "ACC", "BACKUP", 25),
    ("E13", "Kesar Kitchen", "NDR", "BACKUP", 25),
    ("E14", "Kesar Kitchen", "CS", "BACKUP", 50),
    ("E05", "Kesar Kitchen", "CS", "BACKUP", 50),
    ("E15", "Nimbu Naturals", "CS", "BACKUP", 60),
    ("E08", "Himalayan Brew", "CS", "BACKUP", 60),
    ("E10", "Peak Performance", "CS", "BACKUP", 60),
    ("E17", "Urban Tandoor", "NDR", "BACKUP", 40),
    ("E22", "Darjeeling Leaf", "CS", "BACKUP", 60),
    ("E26", "Marine Drive Apparel", "CS", "BACKUP", 60),
]

# Pod leads are trained backups on every line in their pod (added in seed).
LEAD_BACKUP_ALL_POD_LINES = True

# employee code, start, end, type, status
LEAVES = [
    ("E25", "2026-12-21", "2026-12-23", "PL", "APPROVED"),       # only person on Bloom Basket ACC
    ("E03", "2026-12-22", "2026-12-22", "PL", "APPROVED"),       # ...and the East lead, her only backup
    ("E05", "2026-12-08", "2026-12-10", "PL", "APPROVED"),
    ("E28", "2026-12-15", "2026-12-17", "SL", "APPROVED"),
    ("E27", "2026-12-26", "2026-12-26", "COMP_OFF", "APPROVED"),
    ("E14", "2026-12-26", "2026-12-26", "COMP_OFF", "APPROVED"),
    ("E23", "2026-12-28", "2026-12-28", "PL", "PENDING"),
]

# Google Calendar "public holidays" (mock). National list applies to everyone;
# regional calendars add state holidays for employees based there.
HOLIDAYS = {
    "IN-NATIONAL": [
        ("2026-01-26", "Republic Day"), ("2026-03-04", "Holi"), ("2026-08-15", "Independence Day"),
        ("2026-10-02", "Gandhi Jayanti"), ("2026-10-20", "Dussehra"), ("2026-11-08", "Diwali"),
        ("2026-12-25", "Christmas"),
        ("2027-01-26", "Republic Day"), ("2027-03-22", "Holi"), ("2027-08-15", "Independence Day"),
        ("2027-10-02", "Gandhi Jayanti"), ("2027-10-09", "Dussehra"), ("2027-10-29", "Diwali"),
        ("2027-12-25", "Christmas"),
    ],
    "IN-WB": [("2026-10-17", "Durga Puja (Saptami)"), ("2026-10-18", "Durga Puja (Ashtami)"),
              ("2026-10-19", "Durga Puja (Navami)")],
    "IN-MH": [("2026-05-01", "Maharashtra Day"), ("2026-09-14", "Ganesh Chaturthi"),
              ("2027-05-01", "Maharashtra Day")],
}

DEMO_USERS = [
    # username, role, scope_level, scope (pod id / brand name / employee code / None)
    ("admin", "SUPER_ADMIN", "COMPANY", None),
    ("ops", "OPS_MANAGER", "COMPANY", None),
    ("lead.south", "POD_LEAD", "POD", "pod-south"),
    ("lead.north", "POD_LEAD", "POD", "pod-north"),
    ("brand.kesar", "BRAND_OWNER", "BRAND", "Kesar Kitchen"),
    ("meera", "EMPLOYEE", "SELF", "E12"),
    ("auditor", "AUDITOR", "COMPANY", None),
]

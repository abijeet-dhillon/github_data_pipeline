import os, sys, json, datetime as dt, requests
from collections import Counter, defaultdict


GITHUB_TOKEN = ""    
OWNER        = "prettier"
REPO         = "prettier"
BRANCH          = "main"        
FILE_PATH    = "README.md"   
GRAPHQL_URL = "https://api.github.com/graphql"
OUTPUT_DIR  = "output"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "blame_sample.json")


QUERY_BY_REF = """
query BlameByRef($owner:String!, $name:String!, $qualified:String!, $path:String!) {
  repository(owner:$owner, name:$name) {
    ref(qualifiedName:$qualified) {
      name
      target {
        __typename
        ... on Commit {
          oid
          blame(path:$path) {
            ranges {
              startingLine
              endingLine
              age
              commit {
                oid
                committedDate
                message
                author {
                  name
                  email
                  user { login }
                }
              }
            }
          }
        }
      }
    }
  }
}
"""


QUERY_BY_OBJECT = """
query BlameByObject($owner:String!, $name:String!, $ref:String!, $path:String!) {
  repository(owner:$owner, name:$name) {
    object(expression:$ref) {
      __typename
      ... on Commit {
        oid
        blame(path:$path) {
          ranges {
            startingLine
            endingLine
            age
            commit {
              oid
              committedDate
              message
              author {
                name
                email
                user { login }
              }
            }
          }
        }
      }
    }
  }
}
"""


def run_query(q: str, variables: dict):
    if not GITHUB_TOKEN or GITHUB_TOKEN.endswith("XXXX"):
        print("ERROR: Set GITHUB_TOKEN at top of file.", file=sys.stderr)
        sys.exit(1)
    r = requests.post(
        GRAPHQL_URL,
        json={"query": q, "variables": variables},
        headers={
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "cosc448-blame-sampler",
        },
        timeout=30,
    )
    if r.status_code != 200:
        raise RuntimeError(f"GraphQL HTTP {r.status_code}: {r.text[:500]}")
    data = r.json()
    if "errors" in data and data["errors"]:
        raise RuntimeError(f"GraphQL error: {data['errors'][0]}")
    return data["data"]


def short_sha(oid: str) -> str:
    return oid[:7] if oid else "unknown"


def one_line(msg: str) -> str:
    return (msg or "").splitlines()[0].strip()


def author_key_from_commit_author(author_obj: dict) -> str:
    login = ((author_obj.get("user") or {}).get("login")) or ""
    name  = author_obj.get("name")  or ""
    email = author_obj.get("email") or ""
    return login or name or email or "unknown"


def summarize_blame(blame_ranges):
    lines_by_author = Counter()
    ranges_by_author = defaultdict(list)
    examples, total_lines = [], 0

    for rg in blame_ranges:
        start, end = int(rg["startingLine"]), int(rg["endingLine"])
        count = max(0, end - start + 1)
        total_lines += count

        c = rg.get("commit") or {}
        a = (c.get("author") or {})
        who = author_key_from_commit_author(a)

        lines_by_author[who] += count
        ranges_by_author[who].append({
            "start": start,
            "end": end,
            "count": count,
            "age": rg.get("age"),
            "commit_sha": c.get("oid"),
            "committed_date": c.get("committedDate"),
            "message": one_line(c.get("message")),
        })

        if len(examples) < 5:
            examples.append({
                "lines": {"start": start, "end": end, "count": count},
                "age": rg.get("age"),
                "commit_sha": short_sha(c.get("oid", "")),
                "committed_date": c.get("committedDate"),
                "who": who,
                "message": one_line(c.get("message", "")),
            })

    return total_lines, lines_by_author, ranges_by_author, examples


def main():
    qualified = BRANCH if BRANCH.startswith("refs/") else f"refs/heads/{BRANCH}"
    blame = []
    root_commit_oid = None

    try:
        data = run_query(QUERY_BY_REF, {
            "owner": OWNER, "name": REPO, "qualified": qualified, "path": FILE_PATH
        })
        target = (((data.get("repository") or {}).get("ref") or {}).get("target") or {})
        if target.get("__typename") == "Commit":
            root_commit_oid = target.get("oid")
            blame = (((target.get("blame") or {}).get("ranges")) or [])
        else:
            raise RuntimeError("Ref did not resolve to a Commit")
    except Exception:
        data = run_query(QUERY_BY_OBJECT, {
            "owner": OWNER, "name": REPO, "ref": BRANCH, "path": FILE_PATH
        })
        obj = ((data.get("repository") or {}).get("object") or {})
        if obj.get("__typename") != "Commit":
            print(f"ERROR: Resolved object is {obj.get('__typename') or 'None'}, not Commit. Check REF.", file=sys.stderr)
            sys.exit(3)
        root_commit_oid = obj.get("oid")
        blame = (((obj.get("blame") or {}).get("ranges")) or [])

    if not blame:
        print("Blame ranges are empty (binary file, bad path, or blame unavailable).", file=sys.stderr)
        sys.exit(4)

    total, by_author, ranges_by_author, examples = summarize_blame(blame)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    authors_sorted = sorted(by_author.items(), key=lambda kv: kv[1], reverse=True)
    authors_detail = [
        {
            "author": author,
            "total_lines": lines,
            "ranges": ranges_by_author[author],  
        }
        for author, lines in authors_sorted
    ]

    doc = {
        "repository": f"{OWNER}/{REPO}",
        "ref": BRANCH,
        "file_path": FILE_PATH,
        "root_commit_oid": root_commit_oid,
        "ranges_count": len(blame),
        "total_lines": total,
        "authors": authors_detail,
        "examples": examples, 
        "generated_at": (
            dt.datetime.now(dt.timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        ),
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)

    print("Done retrieving git blame sample data. View in output/blame_sample.json.")

    # ---- Console summary (all authors) ----
    print(f"\nRepository : {OWNER}/{REPO}")
    print(f"File       : {FILE_PATH} @ {REF}")
    print(f"Ranges     : {len(blame)}")
    print(f"Lines (sum): {total}")
    print(f"Wrote JSON : {OUTPUT_FILE}\n")

    print("Authors by total lines (all):")
    for author, lines in authors_sorted:
        print(f"  {author or 'unknown':<25} {lines:>6}")

    print("\nDetailed line ranges per author:")
    for author, lines in authors_sorted:
        print(f"\n— {author or 'unknown'} ({lines} lines) —")
        for rg in ranges_by_author[author]:
            date = rg["committed_date"]
            try:
                date = dt.datetime.fromisoformat(date.replace("Z", "+00:00")).strftime("%Y-%m-%d")
            except Exception:
                pass
            sha7 = short_sha(rg["commit_sha"] or "")
            print(f"  lines {rg['start']:>5}-{rg['end']:<5} ({rg['count']:>4})  {sha7}  {date}  {rg['message']}")


if __name__ == "__main__":
    main()
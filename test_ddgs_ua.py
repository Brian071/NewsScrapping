from duckduckgo_search import DDGS
import random

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0.3 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 14_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Mobile/15E148 Safari/604.1"
]

def test_ddgs_headers():
    ua = random.choice(USER_AGENTS)
    print(f"Testing with User-Agent: {ua}")

    try:
        # Attempt to pass headers. Note: The exact signature depends on the version.
        # Newer versions might accept headers in init or not at all.
        with DDGS(headers={"User-Agent": ua}, timeout=20) as ddgs:
            results = list(ddgs.news("Tesla", max_results=5))
            print(f"Success! Found {len(results)} results.")
            for r in results:
                print(f" - {r.get('title')}")

    except TypeError:
        print("DDGS constructor might not accept 'headers'. Trying without...")
        try:
             with DDGS() as ddgs:
                # Some versions rely on the library to handle UAs.
                results = list(ddgs.news("Tesla", max_results=5))
                print(f"Success (default)! Found {len(results)} results.")
        except Exception as e:
            print(f"Failed default: {e}")

    except Exception as e:
        print(f"Failed with custom UA: {e}")

if __name__ == "__main__":
    test_ddgs_headers()

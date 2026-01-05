import os
import sys
import json
import argparse
from datetime import datetime

# Add parent directory to path for imports
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

# Local imports from the repository
from agent.llm_generator import generate_post
from agent.linkedin_poster import post_to_linkedin


def build_full_text(post: dict) -> str:
    """Return the final text to post on LinkedIn.
    Ensures hashtags are always appended to the body.
    """
    body = (post.get("body") or "").strip()
    hashtags = post.get("hashtags", [])
    
    if not body:
        # Fallback: compose minimal content from title and hashtags
        title = post.get("title", "LinkedIn Update")
        tag_str = (" ".join(hashtags)).strip()
        body = f"{title}\n\n{tag_str}".strip()
        return body
    
    # Check if hashtags are already in the body
    has_hashtags = any(tag in body for tag in hashtags) if hashtags else False
    
    # If hashtags exist and aren't in the body, append them
    if hashtags and not has_hashtags:
        tag_str = " ".join(hashtags)
        body = f"{body}\n\n{tag_str}"
    
    return body


def save_preview(post: dict, full_text: str, path_txt: str = "post_preview.txt") -> None:
    # Sanitize path to prevent directory traversal
    safe_path = os.path.basename(path_txt)
    if not safe_path or safe_path in ('.', '..'):
        safe_path = "post_preview.txt"
    
    preview = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "title": post.get("title"),
        "seo_score": post.get("seo_score"),
        "seo_keywords": post.get("seo_keywords", []),
        "hashtags": post.get("hashtags", []),
        "text": full_text,
    }
    with open(safe_path, "w", encoding="utf-8") as f:
        f.write(preview["text"])  # write the shareable text itself for quick copy
    # Also keep a JSON artifact next to it
    with open("latest_post.json", "w", encoding="utf-8") as jf:
        json.dump(preview, jf, indent=2)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate and (optionally) post a LinkedIn update for a niche topic.")
    parser.add_argument("--topic", required=False, default="AI-based Genetic Mutations We Should Fear", help="Topic to generate the post about")
    parser.add_argument("--dry-run", action="store_true", help="Only generate and save preview without posting to LinkedIn")
    args = parser.parse_args()

    topic = args.topic

    try:
        # Generate the post via OpenRouter DeepSeek R1 (configured in llm_generator)
        post = generate_post(niche=topic)
        if not post:
            print("Failed to generate post.")
            return 1

        full_text = build_full_text(post)
        save_preview(post, full_text)
        print("Generated post preview saved to post_preview.txt and latest_post.json")

        if args.dry_run:
            print("Dry run enabled — not posting to LinkedIn.")
            return 0

        # Respect ENABLE_POST env (default true)
        enable_post = os.getenv("ENABLE_POST", "true").lower() == "true"
        if not enable_post:
            print("ENABLE_POST is not true — skipping LinkedIn post. Preview saved.")
            return 0

        print("Posting to LinkedIn…")
        success = post_to_linkedin(full_text)
        if success:
            print("Posted successfully. Screenshots saved as before_post.png and after_click_post.png if available.")
            return 0
        else:
            print("Posting may have failed — please check logs and screenshots.")
            return 2

    except Exception as e:
        print(f"Error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
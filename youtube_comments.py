import openai
import os  # Add this import

def fetch_comments(youtube, video_id):
    """Fetch top-level comments from a YouTube video."""
    try:
        request = youtube.commentThreads().list(
            part="snippet",
            videoId=video_id,
            maxResults=50
        )
        response = request.execute()
        comments = [
            {
                "commentId": item["id"],
                "text": item["snippet"]["topLevelComment"]["snippet"]["textOriginal"],
                "author": item["snippet"]["topLevelComment"]["snippet"]["authorDisplayName"]
            }
            for item in response.get("items", [])
        ]
        return comments
    except Exception as e:
        print(f"Error fetching comments: {e}")
        return []

def generate_reply(comment_text):
    """Generate a reply using OpenAI GPT."""
    prompt = f"Write an engaging reply to the following YouTube comment:\n\nComment: {comment_text}\n\nReply:"
    try:
        response = openai.Completion.create(
            engine="text-davinci-003",
            prompt=prompt,
            max_tokens=50
        )
        return response.choices[0].text.strip()
    except Exception as e:
        print(f"Error generating reply: {e}")
        return "Thank you for your comment!"

def post_reply(youtube, comment_id, reply_text):
    """Post a reply to a YouTube comment."""
    try:
        request = youtube.comments().insert(
            part="snippet",
            body={
                "snippet": {
                    "parentId": comment_id,
                    "textOriginal": reply_text
                }
            }
        )
        response = request.execute()
        print(f"Reply posted: {response['snippet']['textDisplay']}")
        return response
    except Exception as e:
        print(f"Error posting reply: {e}")
        return None

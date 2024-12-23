# File: app.py

import os
import openai
from flask import Flask, request, jsonify, render_template
from youtube_auth import authenticate_youtube_api
from youtube_comments import fetch_comments, post_reply
from googleapiclient.discovery import build
import time
from flask_cors import CORS
CORS(app)


# Set API keys and URLs
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "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")  # Ensure this is set in your environment
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "AIzaSyA8qclHhZNDRlaJ2ZBUmy-3ocO638rhXFE")  # Default fallback for YouTube API key
ZAPIER_WEBHOOK_URL = os.getenv(
    "ZAPIER_WEBHOOK_URL", "https://hooks.zapier.com/hooks/catch/20851872/2it5auu/"
)  # Replace with your Zapier webhook URL

if not OPENAI_API_KEY or not YOUTUBE_API_KEY:
    raise EnvironmentError("Missing API keys. Ensure YOUTUBE_API_KEY and OPENAI_API_KEY are set in the environment.")

# Set OpenAI API key
openai.api_key = OPENAI_API_KEY
print(f"OpenAI API Key being used: {openai.api_key}")  # Debug line

# Global set to store processed comment IDs
processed_comment_ids = set()

# Flask App
app = Flask(__name__)
CORS(app)  # Enable CORS


@app.route('/')
def home():
    """
    Render the HTML UI for the YouTube Comment Agent.
    """
    return render_template('index.html')

@app.route('/callback')
def oauth2callback():
    # Initialize the flow using the client_secrets.json
    flow = Flow.from_client_secrets_file(
        'client_secrets.json',
        scopes=['https://www.googleapis.com/auth/userinfo.profile', 'https://www.googleapis.com/auth/userinfo.email'],
        redirect_uri='https://youtube-comment-agent.vercel.app/callback'
    )
    # Fetch the authorization response
    flow.fetch_token(authorization_response=request.url)
    credentials = flow.credentials

    # Use the credentials to access user info or save them
    session['credentials'] = {
        'token': credentials.token,
        'refresh_token': credentials.refresh_token,
        'token_uri': credentials.token_uri,
        'client_id': credentials.client_id,
        'client_secret': credentials.client_secret,
        'scopes': credentials.scopes
    }
    return "Authentication successful!"

if __name__ == '__main__':
    app.run()

@app.route('/favicon.ico')
def favicon():
    """
    Handle favicon requests to avoid unnecessary 404s.
    """
    return "", 204

# In-memory storage for replies awaiting approval
pending_replies = []


@app.route('/process', methods=['POST'])
def process():
    """
    Mock `/process` endpoint to test Vercel deployment.
    """
    data = request.get_json()
    url = data.get("url")
    mood = data.get("mood", "casual")
    role = data.get("role", "community")

    # Log request for debugging
    print(f"Received URL: {url}, Mood: {mood}, Role: {role}")

    # Return a mock response
    return jsonify({
        "message": "Processed comments successfully!",
        "pending_replies": [
            {
                "commentId": "12345",
                "commentText": "This is a mock comment.",
                "generatedReply": f"This is a mock reply in {mood} mood as a {role}.",
                "approvedReply": None,
                "author": "AuthorChannel123"
            }
        ]
    })

@app.route('/approve', methods=['POST'])
def approve():
    """
    Mock `/approve` endpoint to test Vercel deployment.
    """
    data = request.get_json()
    approved_replies = data.get("approvedReplies", [])

    # Log approval details for debugging
    print(f"Approved Replies: {approved_replies}")

    return jsonify({"message": f"Approved {len(approved_replies)} replies!"})

if __name__ == "__main__":
    app.run(debug=True)

@app.route('/process', methods=['POST'])
def process_youtube_comments():
    """
    Fetch comments (including subcomments), filter out comments already answered by the bot,
    heart the comments, generate replies, and prepare them for manual approval.
    """
    try:
        global pending_replies  # List to store replies awaiting approval
        pending_replies = []  # Reset pending replies for each new video processing

        # Parse incoming JSON payload
        data = request.get_json()
        video_url = data.get("url")
        role = data.get("role", "community")  # Default role is community member

        if not video_url:
            return jsonify({"error": "YouTube video URL is required"}), 400

        # Extract the video ID from the URL
        video_id = extract_video_id(video_url)
        if not video_id:
            return jsonify({"error": "Invalid YouTube video URL"}), 400

        # Authenticate YouTube API
        youtube = authenticate_youtube_api()

        # Fetch the bot's own channel ID
        channel_response = youtube.channels().list(part="id", mine=True).execute()
        bot_channel_id = channel_response["items"][0]["id"]
        print(f"Bot's channel ID: {bot_channel_id}")

        # Fetch comments from the YouTube video
        comments = fetch_comments_with_replies(youtube, video_id, bot_channel_id)

        if not comments:
            print("No comments found on the video.")
            return jsonify({"error": "No comments found on the video"}), 404

        # Iterate through fetched comments
        for comment in comments:
            try:
                # Validate comment structure
                comment_id = comment["commentId"]
                author_channel_id = comment["authorChannelId"]
                comment_text = comment["text"]
                already_replied_by_bot = comment["alreadyRepliedByBot"]

                # Skip duplicate comments
                if comment_id in processed_comment_ids:
                    print(f"Skipping duplicate comment ID: {comment_id}")
                    continue

                # Skip comments made by the bot itself if role is "owner"
                if role == "owner" and author_channel_id == bot_channel_id:
                    print(f"Skipping bot's own comment: {comment_text}")
                    continue

                # Skip comments already replied to by the bot
                if already_replied_by_bot:
                    print(f"Skipping already-replied comment: {comment_text}")
                    continue

                # Heart the comment (if the bot is the channel owner)
                if role == "owner":
                    try:
                        youtube.comments().setModerationStatus(
                            id=comment_id,
                            moderationStatus="published",
                            banAuthor=False
                        ).execute()
                        print(f"Hearted comment: {comment_text}")
                    except Exception as e:
                        print(f"Failed to heart comment: {comment_text}. Error: {e}")

                # Generate a reply using OpenAI
                reply = generate_reply(
                    comment_text, 
                    role, 
                    data.get("mood", "casual"), 
                    data.get("appendSignature", False)  # Pass appendSignature flag
                )

                # Add the comment and reply to pending replies for manual approval
                pending_replies.append({
                    "commentId": comment_id,
                    "commentText": comment_text,
                    "generatedReply": reply,
                    "approvedReply": None,  # Placeholder for manual approval
                    "author": author_channel_id
                })

                # Mark the comment as processed after successful handling
                processed_comment_ids.add(comment_id)

            except Exception as e:
                print(f"Error processing comment: {comment}. Error: {e}")

        # Return prepared replies for manual approval
        return jsonify({
            "message": "Replies prepared for approval.",
            "pending_replies": pending_replies
        })
    except Exception as e:
        print(f"Error in /process endpoint: {e}")
        return jsonify({"error": str(e)}), 500


def already_replied_by_bot(replies, bot_channel_id):
    """
    Checks if the bot has already replied to a given comment.
    Args:
        replies (list): List of reply objects under a comment.
        bot_channel_id (str): The bot's YouTube channel ID.
    Returns:
        bool: True if the bot has replied to the comment, False otherwise.
    """
    if not replies:
        return False  # No replies exist

    for reply in replies:
        reply_author_id = reply["snippet"]["authorChannelId"]["value"]
        if reply_author_id == bot_channel_id:
            return True  # Bot has replied

    return False  # No reply from the bot


def fetch_comments_with_replies(youtube, video_id, bot_channel_id):
    """
    Fetch comments and their replies from the YouTube video and mark those already replied by the bot.
    """
    try:
        comments = []
        request = youtube.commentThreads().list(
            part="snippet,replies",
            videoId=video_id,
            maxResults=100,
            moderationStatus="published"
        )

        while request:
            response = request.execute()
            for item in response.get("items", []):
                snippet = item["snippet"]["topLevelComment"]["snippet"]
                comment_id = item["id"]

                # Skip comments already processed
                if comment_id in processed_comment_ids:
                    print(f"Skipping duplicate comment ID: {comment_id}")
                    continue

                # Check if the bot has already replied to this comment
                replies = item.get("replies", {}).get("comments", [])
                already_replied = already_replied_by_bot(replies, bot_channel_id)

                # Add to comments list
                comments.append({
                    "commentId": comment_id,
                    "text": snippet["textDisplay"],
                    "authorChannelId": snippet["authorChannelId"]["value"],
                    "alreadyRepliedByBot": already_replied
                })

            request = youtube.commentThreads().list_next(request, response)

        return comments
    except Exception as e:
        print(f"Error fetching comments with replies: {e}")
        return []




@app.route('/approve', methods=['POST'])
def approve_replies():
    """
    Process approved replies and post them to YouTube.
    """
    try:
        print("✅ Received request at /approve")

        # Parse the incoming JSON payload
        data = request.get_json(silent=True)
        if not data:
            print("❌ Error: No JSON payload received.")
            return jsonify({"error": "Invalid JSON payload."}), 400

        # Extract 'approvedReplies' from the JSON payload
        approved_replies = data.get('approvedReplies', [])
        if not approved_replies:
            print("❌ Error: No approved replies provided.")
            return jsonify({"error": "No approved replies provided."}), 400

        youtube = authenticate_youtube_api()
        approved_count = 0

        # Process approved replies
        for reply in approved_replies:
            comment_id = reply.get('commentId')
            approved_reply = reply.get('approvedReply')

            if not comment_id or not approved_reply:
                print(f"❌ Skipping invalid reply: {reply}")
                continue

            try:
                print(f"✅ Posting reply: Comment ID = {comment_id}, Reply = {approved_reply}")
                post_reply(youtube, comment_id, approved_reply)
                approved_count += 1
            except Exception as e:
                print(f"❌ Error posting reply for Comment ID {comment_id}: {e}")

        print(f"✅ Successfully posted {approved_count} replies.")
        return jsonify({"message": f"{approved_count} replies posted successfully."}), 200
    except Exception as e:
        print(f"❌ Unexpected server error: {e}")
        return jsonify({"error": str(e)}), 500



def extract_video_id(url):
    """
    Extracts the video ID from a YouTube URL.
    """
    try:
        if "v=" in url:
            return url.split("v=")[1].split("&")[0]
        elif "youtu.be/" in url:
            return url.split("youtu.be/")[1].split("?")[0]
        return None
    except Exception:
        return None





def generate_reply(comment_text, role, mood="casual", append_signature=False):
    """
    Generate a reply to a YouTube comment using OpenAI GPT based on the user's role and mood.
    Optionally append 'Cheers, Abhi' as a signature if the user enables it.
    """
    try:
        # Role-specific instructions
        role_instructions = {
            "owner": (
                "You are the owner of the YouTube channel. Respond professionally, taking credit for the content, "
                "showing gratitude, and keeping responses concise and engaging."
            ),
            "community": (
                "You are a community member. Engage in a friendly, conversational tone, adding value to the conversation "
                "without taking credit for the content or saying 'thank you.' Keep responses short and meaningful."
            ),
        }

        # Mood-specific instructions
        mood_instructions = {
            "funny": "Your tone should be lighthearted and humorous, with playful remarks or jokes.",
            "casual": "Your tone should be friendly, casual, and conversational.",
            "professional": "Your tone should be formal, respectful, and concise.",
        }

        # Combine role and mood instructions
        role_text = role_instructions.get(role, role_instructions["community"])
        mood_text = mood_instructions.get(mood, mood_instructions["casual"])

        # Generate a reply using OpenAI
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {
                    "role": "system",
                    "content": f"{role_text} {mood_text} Your replies should feel authentic, concise, and context-aware."
                },
                {
                    "role": "user",
                    "content": f"Comment: {comment_text}\nReply accordingly."
                }
            ],
            max_tokens=80,
            temperature=0.7
        )

        reply = response['choices'][0]['message']['content'].strip()

        # Conditionally append the signature
        if role == "owner" and append_signature:
            reply += " Cheers, Abhi."

        return reply
    except Exception as e:
        print(f"Error generating reply for role {role} and mood {mood}: {e}")
        return "We appreciate your comment and support!"






if __name__ == "__main__":
    app.run(debug=True)

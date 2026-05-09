import os
import time
from supabase import create_client, Client

# Retrieve Supabase configurations from environment variables
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://your-project-ref.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "your-anon-or-service-role-key")

# Initialize Supabase client
try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    print(f"Warning: Failed to initialize Supabase client. Error: {e}")

def run_worker():
    """
    Continuously polls the 'votes_queue' table to process messages.
    Acts as the worker layer, replacing GCP Pub/Sub pull subscription.
    """
    print("Starting Supabase Worker Service.")
    print("Polling 'votes_queue' table for new votes...\n")
    
    try:
        while True:
            # 1. PULL: Fetch the oldest unprocessed vote from the queue
            # Selecting 1 row to mimic processing a single message
            response = supabase.table("votes_queue").select("*").order("created_at").limit(1).execute()
            
            # response.data contains the list of rows
            queue_data = response.data
            
            if not queue_data:
                # No messages in queue, sleep briefly before polling again
                time.sleep(1)
                continue
                
            vote = queue_data[0]
            queue_id = vote.get("id")
            user_id = vote.get("user_id")
            poll_id = vote.get("poll_id")
            choice = vote.get("choice")
            timestamp = vote.get("timestamp")
            
            print(f"Received at worker: {user_id} | Time: {time.time()}")
            
            # 2. PROCESS & IDEMPOTENCY
            # We attempt to insert this into the permanent 'votes' table.
            # The 'votes' table has a UNIQUE constraint on (user_id, poll_id).
            # If it's a duplicate, Supabase (Postgres) will throw a duplicate key violation.
            try:
                # Prepare final record
                final_vote = {
                    "user_id": user_id,
                    "poll_id": poll_id,
                    "choice": choice,
                    "timestamp": timestamp
                }
                
                # Insert into final table
                supabase.table("votes").insert(final_vote).execute()
                print(f"Processed vote: {user_id} | Poll: {poll_id}")
                
            except Exception as e:
                error_str = str(e)
                if "duplicate key value" in error_str or "23505" in error_str:
                    print(f"Duplicate vote detected and rejected for user: {user_id}. Idempotency enforced.")
                else:
                    print(f"Error processing vote: {e}")
            
            # 3. ACKNOWLEDGE: Delete the message from the queue table
            # Regardless of whether it was successfully inserted or skipped as a duplicate, 
            # we must remove it from the queue so it isn't processed again.
            supabase.table("votes_queue").delete().eq("id", queue_id).execute()
            
            # Small delay to prevent runaway CPU usage
            time.sleep(0.1)
            
    except KeyboardInterrupt:
        print("\nWorker shutting down.")

if __name__ == "__main__":
    run_worker()

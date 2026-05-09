# Distributed Voting System (Supabase Edition)

A fault-tolerant distributed voting system demonstrating Edge-Cloud architecture, asynchronous messaging, and event-driven processing. Originally designed for GCP, this architecture has been ported to use **Supabase** (a free, open-source Postgres platform) to avoid cloud subscription costs while retaining full distributed systems concepts.

## Architecture

This system implements the following event-driven pipeline:
`Edge Nodes -> Local API (Ingestion) -> Supabase Queue (Messaging) -> Worker Service -> Supabase Database (Storage)`

1. **Edge Nodes (`edge_node/`)**: Simulate user devices independently generating and sending synthetic votes to the API layer via HTTP. It includes retry logic and simulated message duplication for testing idempotency.
2. **API Ingestion (`api_service/`)**: A fast, stateless Flask API that receives requests and inserts them instantly into a Supabase `votes_queue` table without blocking.
3. **Worker Service (`worker_service/`)**: A continuous background service that polls the `votes_queue` table, attempts to save the vote into the final `votes` table, and then deletes the queue message (acting as an ACK). It enforces **Idempotency** using Postgres UNIQUE constraints to reject duplicate votes.
4. **Supabase Postgres**: The relational persistent storage layer holding both the temporary message queue and the final, deduplicated votes.

---

## Setup and Deployment

### 1. Supabase Project Preparation
1. Go to [Supabase](https://supabase.com/) and create a free project.
2. Once created, go to **Project Settings -> API** and copy your **Project URL** and **anon `public` API Key**.
3. Go to the **SQL Editor** in the Supabase sidebar and run the following SQL snippet to create our required tables:

```sql
-- 1. Create the Queue table (acts like Pub/Sub buffer)
CREATE TABLE votes_queue (
    id SERIAL PRIMARY KEY,
    user_id UUID NOT NULL,
    poll_id TEXT NOT NULL,
    choice TEXT NOT NULL,
    timestamp FLOAT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- 2. Create the final Storage table (acts like Firestore)
CREATE TABLE votes (
    id SERIAL PRIMARY KEY,
    user_id UUID NOT NULL,
    poll_id TEXT NOT NULL,
    choice TEXT NOT NULL,
    timestamp FLOAT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL,
    -- This constraint guarantees IDEMPOTENCY. It prevents duplicate votes.
    UNIQUE (user_id, poll_id)
);
```

### 2. Run the API Ingestion Layer
Open a terminal window. This API will run locally on port 8080 and forward votes to Supabase.
```bash
cd api_service
pip install -r requirements.txt
export SUPABASE_URL="https://[YOUR-PROJECT-ID].supabase.co"
export SUPABASE_KEY="[YOUR-ANON-KEY]"
python main.py
```

### 3. Run the Worker Service
Open a second terminal window. The worker runs continuously to process background jobs from the queue table.
```bash
cd worker_service
pip install -r requirements.txt
export SUPABASE_URL="https://[YOUR-PROJECT-ID].supabase.co"
export SUPABASE_KEY="[YOUR-ANON-KEY]"
python main.py
```

### 4. Run Edge Nodes (Client Simulation)
Open a third terminal window. This represents the edge device generating user data.
```bash
cd edge_node
pip install -r requirements.txt
# Point to your local API
export API_URL="http://127.0.0.0:8080/vote"
python main.py
```

---

## Fault Injection Testing

1. **Message Duplication (Idempotency)**:
   - Edit `edge_node/main.py` and uncomment the duplicate `send_vote(vote)` line.
   - Run the edge node.
   - **Observation**: The API queues both. The worker processes both. For the first one, it inserts successfully. For the second one, it throws a Postgres Duplicate Key error (Idempotency successfully enforced). Both get removed from the queue.

2. **Worker Failure (Downtime & Recovery)**:
   - Stop the running worker process terminal (`Ctrl+C`).
   - Keep the Edge Node running.
   - **Observation**: Check your Supabase Table Editor. You will see the `votes_queue` table filling up with unprocessed messages, while the `votes` table stops updating.
   - **Recovery**: Restart the worker process. It will automatically reconnect, pull the buffered backlog from the queue, and successfully update the final votes table without losing any data.

---

## Reflection and Analysis

### Mariann Mesa

**System Performance & Distributed Execution**
Transitioning from a traditional, sequential execution model to a distributed, event-driven architecture fundamentally changed how data is handled. In a standard monolithic setup, an edge node would have to wait for the server to fully process the vote and save it to the database before receiving a response. By implementing a non-blocking ingestion API, the edge nodes experienced significantly lower latency. The API simply dropped the vote into the Supabase `votes_queue` table and instantly returned a success response. This decoupled the heavy lifting of deduplication and final storage from the fast-paced data collection at the edge.

**Fault Tolerance & Resiliency**
The true value of this distributed architecture became obvious during the simulated worker downtime. When the worker service was intentionally stopped, the system did not crash, nor were any votes lost. Instead, the edge nodes continued generating data, and the API continued happily queuing those votes into the temporary Postgres table. Once the worker was brought back online, it smoothly pulled the backlog of messages from the queue and processed them into the final table. This demonstrated how message queues act as a critical shock absorber, preventing backend outages from affecting the user experience at the edge.

**Data Consistency & Idempotency**
One of the main challenges in distributed systems is handling duplicate messages caused by network retries. During our fault injection test, I deliberately configured the edge node to send the same vote twice. Because the worker layer enforces idempotency using a `UNIQUE(user_id, poll_id)` constraint in the Supabase PostgreSQL database, the duplicate vote was safely rejected. The worker caught the `23505 Duplicate Key Violation` error, discarded the duplicate, and moved on. This guaranteed that the final `votes` table maintained strict data consistency without counting the same vote multiple times.

**Trade-offs**
While the distributed architecture provides massive benefits in fault tolerance and scalability, it undeniably introduces significant complexity. Instead of managing a single codebase, we now have to coordinate three distinct components (Edge, API, Worker) and monitor two different database tables. Debugging also became harder, as tracing a single vote requires looking at logs across multiple services. However, for a high-traffic, real-world application like a voting system where data loss is unacceptable, this added operational complexity is a necessary trade-off for the resilience and scalability it provides.

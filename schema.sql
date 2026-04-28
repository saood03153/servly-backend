-- ════════════════════════════════════════════════════════
-- SERVLY AI — Full Supabase Database Setup
-- Run this entire file in the Supabase SQL Editor
-- ════════════════════════════════════════════════════════

-- STEP 1: Enable PostGIS
CREATE EXTENSION IF NOT EXISTS postgis;

-- ════════════════════════════════════════════════════════
-- TABLE 1: PROFILES (Seekers + Providers)
-- ════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS profiles (
  id          UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  name        TEXT NOT NULL,
  phone       TEXT UNIQUE NOT NULL,
  role        TEXT CHECK (role IN ('seeker', 'provider')) NOT NULL,
  skills      TEXT[],                              -- e.g. {'Bike Repair','Engine Tune-up'}
  location    GEOGRAPHY(POINT, 4326),              -- PostGIS geography column
  status      TEXT DEFAULT 'offline'
              CHECK (status IN ('online', 'offline', 'busy')),
  fcm_token   TEXT,
  avatar_url  TEXT,
  rating      DECIMAL(3, 2) DEFAULT 5.0,
  total_jobs  INT DEFAULT 0,
  created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ════════════════════════════════════════════════════════
-- TABLE 2: TASKS
-- ════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS tasks (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  seeker_id           UUID REFERENCES profiles(id),
  provider_id         UUID REFERENCES profiles(id),
  problem_description TEXT NOT NULL,
  category            TEXT NOT NULL,
  urgency             TEXT CHECK (urgency IN ('low', 'medium', 'high', 'critical')),
  summary             TEXT,
  status              TEXT DEFAULT 'searching'
                      CHECK (status IN ('searching', 'accepted', 'in_progress', 'completed', 'failed')),
  seeker_location     GEOGRAPHY(POINT, 4326),
  -- Convenience columns (duplicates from geography for easy read)
  lat                 DOUBLE PRECISION,
  lng                 DOUBLE PRECISION,
  created_at          TIMESTAMPTZ DEFAULT NOW(),
  accepted_at         TIMESTAMPTZ,
  completed_at        TIMESTAMPTZ
);

-- ════════════════════════════════════════════════════════
-- TABLE 3: AGENT_LOGS (Real-time UI updates)
-- ════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS agent_logs (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  task_id     UUID REFERENCES tasks(id) ON DELETE CASCADE,
  log_message TEXT NOT NULL,
  log_type    TEXT DEFAULT 'info'
              CHECK (log_type IN ('info', 'success', 'warning', 'error', 'ping')),
  timestamp   TIMESTAMPTZ DEFAULT NOW()
);

-- ════════════════════════════════════════════════════════
-- STEP 3: PostGIS Proximity Search Function
-- ════════════════════════════════════════════════════════
CREATE OR REPLACE FUNCTION find_nearby_providers(
  lat          DOUBLE PRECISION,
  lng          DOUBLE PRECISION,
  radius_km    DOUBLE PRECISION DEFAULT 5.0,
  skill_filter TEXT DEFAULT NULL,
  max_results  INT DEFAULT 5
)
RETURNS TABLE (
  id          UUID,
  name        TEXT,
  phone       TEXT,
  role        TEXT,
  skills      TEXT[],
  status      TEXT,
  avatar_url  TEXT,
  rating      DECIMAL,
  total_jobs  INT,
  lat         DOUBLE PRECISION,
  lng         DOUBLE PRECISION,
  distance    DOUBLE PRECISION,
  fcm_token   TEXT
) AS $$
  SELECT
    p.id,
    p.name,
    p.phone,
    p.role,
    p.skills,
    p.status,
    p.avatar_url,
    p.rating,
    p.total_jobs,
    ST_Y(p.location::geometry) AS lat,
    ST_X(p.location::geometry) AS lng,
    ST_Distance(
      p.location::geography,
      ST_SetSRID(ST_MakePoint(lng, lat), 4326)::geography
    ) / 1000.0 AS distance,
    p.fcm_token
  FROM profiles p
  WHERE p.role = 'provider'
    AND p.status = 'online'
    AND ST_DWithin(
      p.location::geography,
      ST_SetSRID(ST_MakePoint(lng, lat), 4326)::geography,
      radius_km * 1000
    )
    AND (skill_filter IS NULL OR skill_filter = ANY(p.skills))
  ORDER BY distance ASC
  LIMIT max_results;
$$ LANGUAGE sql STABLE;

-- ════════════════════════════════════════════════════════
-- STEP 4: Row Level Security
-- ════════════════════════════════════════════════════════
ALTER TABLE profiles   ENABLE ROW LEVEL SECURITY;
ALTER TABLE tasks      ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_logs ENABLE ROW LEVEL SECURITY;

-- Profiles: users read & update their own
CREATE POLICY "Users read own profile"
  ON profiles FOR SELECT USING (auth.uid() = id);

-- Providers are publicly visible for browse/map feature
CREATE POLICY "Anyone reads provider profiles"
  ON profiles FOR SELECT USING (role = 'provider');

CREATE POLICY "Users update own profile"
  ON profiles FOR UPDATE USING (auth.uid() = id);

CREATE POLICY "Users insert own profile"
  ON profiles FOR INSERT WITH CHECK (auth.uid() = id);

-- Tasks: seekers and providers can see their own tasks
CREATE POLICY "Seekers read own tasks"
  ON tasks FOR SELECT USING (auth.uid() = seeker_id);

CREATE POLICY "Providers read assigned tasks"
  ON tasks FOR SELECT USING (auth.uid() = provider_id);

CREATE POLICY "Seekers create tasks"
  ON tasks FOR INSERT WITH CHECK (auth.uid() = seeker_id);

CREATE POLICY "Tasks update by participant"
  ON tasks FOR UPDATE
  USING (auth.uid() = seeker_id OR auth.uid() = provider_id);

-- Agent logs: anyone involved in the task can read
CREATE POLICY "Read logs for own tasks"
  ON agent_logs FOR SELECT
  USING (
    EXISTS (
      SELECT 1 FROM tasks t
      WHERE t.id = agent_logs.task_id
        AND (t.seeker_id = auth.uid() OR t.provider_id = auth.uid())
    )
  );

-- Backend service role can insert logs (bypasses RLS anyway with service key)

-- ════════════════════════════════════════════════════════
-- STEP 5: Enable Real-time
-- ════════════════════════════════════════════════════════
ALTER PUBLICATION supabase_realtime ADD TABLE agent_logs;
ALTER PUBLICATION supabase_realtime ADD TABLE tasks;

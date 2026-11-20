-- Sales pipeline schema for project Argo (PRJ-ARG-5675).
--
-- Proprietary and confidential. Property of Aspida Demo Consulting. Do not distribute.
-- Opportunities move through fixed stages; every change of stage is kept, so the weekly
-- pipeline review can show what moved and what stalled.

CREATE SCHEMA IF NOT EXISTS argo;

CREATE TABLE argo.account (
    account_id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    crm_client_id   text NOT NULL UNIQUE,
    owning_team     text NOT NULL,
    segment         text NOT NULL CHECK (segment IN ('enterprise', 'mid-market', 'small')),
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE argo.opportunity (
    opportunity_id  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    account_id      bigint NOT NULL REFERENCES argo.account (account_id),
    title           text NOT NULL,
    stage           text NOT NULL CHECK (stage IN
                        ('lead', 'qualified', 'proposal', 'negotiation', 'won', 'lost')),
    value_eur       numeric(12, 2) NOT NULL CHECK (value_eur >= 0),
    probability     smallint NOT NULL CHECK (probability BETWEEN 0 AND 100),
    expected_close  date NOT NULL,
    owner_user_id   text NOT NULL,
    updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE argo.stage_change (
    change_id       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    opportunity_id  bigint NOT NULL REFERENCES argo.opportunity (opportunity_id),
    from_stage      text,
    to_stage        text NOT NULL,
    changed_at      timestamptz NOT NULL DEFAULT now(),
    changed_by      text NOT NULL
);

CREATE INDEX opportunity_stage_idx ON argo.opportunity (stage, expected_close);
CREATE INDEX stage_change_opportunity_idx ON argo.stage_change (opportunity_id, changed_at);

-- Keeps the history: every update of the stage writes one row to stage_change.
CREATE FUNCTION argo.record_stage_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' OR NEW.stage IS DISTINCT FROM OLD.stage THEN
        INSERT INTO argo.stage_change (opportunity_id, from_stage, to_stage, changed_by)
        VALUES (NEW.opportunity_id,
                CASE WHEN TG_OP = 'UPDATE' THEN OLD.stage END,
                NEW.stage,
                NEW.owner_user_id);
    END IF;
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

CREATE TRIGGER opportunity_stage_history
    BEFORE INSERT OR UPDATE ON argo.opportunity
    FOR EACH ROW EXECUTE FUNCTION argo.record_stage_change();

-- Weighted pipeline per team and quarter: value times probability, open stages only.
CREATE VIEW argo.weighted_pipeline AS
SELECT a.owning_team,
       date_trunc('quarter', o.expected_close)::date AS quarter,
       count(*)                                      AS opportunities,
       sum(o.value_eur)                              AS total_value,
       sum(o.value_eur * o.probability / 100.0)      AS weighted_value
FROM argo.opportunity o
JOIN argo.account a USING (account_id)
WHERE o.stage NOT IN ('won', 'lost')
GROUP BY a.owning_team, date_trunc('quarter', o.expected_close);

-- Opportunities that have not changed stage for 30 days: the list the sales lead chases.
CREATE VIEW argo.stalled_opportunity AS
SELECT o.opportunity_id,
       o.title,
       o.stage,
       o.owner_user_id,
       o.value_eur,
       max(c.changed_at)                       AS last_moved,
       (now() - max(c.changed_at))::interval   AS idle_for
FROM argo.opportunity o
JOIN argo.stage_change c USING (opportunity_id)
WHERE o.stage NOT IN ('won', 'lost')
GROUP BY o.opportunity_id
HAVING max(c.changed_at) < now() - interval '30 days';

-- Win rate per owner over the last four quarters, for the Argo scorecard.
CREATE VIEW argo.win_rate AS
SELECT o.owner_user_id,
       count(*) FILTER (WHERE o.stage = 'won')  AS won,
       count(*) FILTER (WHERE o.stage = 'lost') AS lost,
       round(100.0 * count(*) FILTER (WHERE o.stage = 'won')
             / nullif(count(*) FILTER (WHERE o.stage IN ('won', 'lost')), 0), 1) AS win_rate_percent
FROM argo.opportunity o
WHERE o.updated_at >= now() - interval '12 months'
GROUP BY o.owner_user_id;

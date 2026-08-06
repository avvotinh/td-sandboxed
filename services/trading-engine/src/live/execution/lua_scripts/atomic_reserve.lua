-- atomic_reserve.lua
-- Atomically reserve `requested` lots against an in-flight reservation
-- counter, rejecting if the new total would exceed `max_total`.
--
-- KEYS[1] = "account:{id}:reserved_lots" — string-encoded number
-- ARGV[1] = requested  (lots being added)
-- ARGV[2] = max_total  (cap on currently_reserved + requested)
-- ARGV[3] = ttl_seconds (TTL refresh on accept; 0 = no TTL)
--
-- Returns: { accepted (1/0), new_reserved_str, previous_reserved_str }
--   - accepted = 1 if reservation succeeded; 0 if rejected
--   - new_reserved_str = the value of the counter AFTER this call (string)
--   - previous_reserved_str = the value BEFORE this call (string)
--
-- Story 10.4 — closes the validate↔send race window (D6) by serialising
-- "reserve in-flight lots" through a single atomic Redis operation.

local key = KEYS[1]
local requested = tonumber(ARGV[1])
local max_total = tonumber(ARGV[2])
local ttl = tonumber(ARGV[3])

if requested == nil or max_total == nil then
  return redis.error_reply("atomic_reserve: requested/max_total must be numbers")
end
if requested < 0 then
  return redis.error_reply("atomic_reserve: requested must be non-negative")
end

local raw = redis.call('GET', key)
local current = 0
if raw ~= false then
  current = tonumber(raw) or 0
end

local new = current + requested
if new > max_total then
  return { 0, tostring(current), tostring(current) }
end

redis.call('SET', key, tostring(new))
if ttl ~= nil and ttl > 0 then
  redis.call('EXPIRE', key, ttl)
end

return { 1, tostring(new), tostring(current) }

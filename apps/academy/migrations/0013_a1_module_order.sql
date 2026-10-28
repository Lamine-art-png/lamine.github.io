-- Restore the exact A1 teaching sequence after an administrator moved
-- "What AI means for agriculture" behind the other three modules.
-- Videos 1-14 stay linked to their original lessons; quizzes remain in their
-- existing modules. No learner progress, certificates or media are modified.
-- Applies only when BOTH the live and draft A1 curricula have exactly the
-- four known active modules. Idempotent and auditable.
--
-- Canonical order:
--  1 mod_a1_1 What AI means for agriculture         (video 1-3, quiz 1)
--  2 mod_a1_2 How agricultural AI works             (video 4-6, quiz 2)
--  3 mod_a1_3 AI across the season                 (video 7-10, quiz 3)
--  4 mod_a1_4 Using AI responsibly                 (video 11-14)

INSERT OR IGNORE INTO audit_log (id, actor_id, action, entity_type, entity_id, detail, created_at)
SELECT 'academy-a1-module-order-0013', NULL, 'course.module_order_repair', 'course', 'crs_a1',
       json_object(
         'reason', 'Restore requested original video 1-14 course sequence',
         'live_before', (SELECT json_group_array(json_object('id', id, 'order', sort_order))
                         FROM (SELECT id, sort_order FROM modules WHERE course_id = 'crs_a1' ORDER BY sort_order, id)),
         'draft_before', (SELECT json_group_array(json_object('id', id, 'order', sort_order))
                          FROM (SELECT id, sort_order FROM draft_modules WHERE course_id = 'crs_a1' ORDER BY sort_order, id)),
         'expected_order', json_array('mod_a1_1', 'mod_a1_2', 'mod_a1_3', 'mod_a1_4'),
         'scope', 'A1 module positions only; lesson/video/progress rows unchanged'
       ),
       strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
WHERE (SELECT COUNT(*) FROM modules WHERE course_id = 'crs_a1') = 4
  AND (SELECT COUNT(*) FROM modules WHERE course_id = 'crs_a1' AND status = 'active'
       AND id IN ('mod_a1_1','mod_a1_2','mod_a1_3','mod_a1_4')) = 4
  AND (SELECT COUNT(*) FROM draft_modules WHERE course_id = 'crs_a1'
       AND id IN ('mod_a1_1','mod_a1_2','mod_a1_3','mod_a1_4')) = 4
  AND (SELECT COUNT(*) FROM draft_modules WHERE course_id = 'crs_a1') = 4
  AND (
    EXISTS (SELECT 1 FROM modules WHERE course_id = 'crs_a1'
            AND sort_order != CASE id WHEN 'mod_a1_1' THEN 1 WHEN 'mod_a1_2' THEN 2 WHEN 'mod_a1_3' THEN 3 WHEN 'mod_a1_4' THEN 4 END)
    OR EXISTS (SELECT 1 FROM draft_modules WHERE course_id = 'crs_a1'
               AND sort_order != CASE id WHEN 'mod_a1_1' THEN 1 WHEN 'mod_a1_2' THEN 2 WHEN 'mod_a1_3' THEN 3 WHEN 'mod_a1_4' THEN 4 END)
  );

UPDATE modules
SET sort_order = CASE id
                   WHEN 'mod_a1_1' THEN 1 WHEN 'mod_a1_2' THEN 2
                   WHEN 'mod_a1_3' THEN 3 WHEN 'mod_a1_4' THEN 4 END,
    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
WHERE course_id = 'crs_a1' AND id IN ('mod_a1_1','mod_a1_2','mod_a1_3','mod_a1_4')
  AND status = 'active'
  AND (SELECT COUNT(*) FROM modules WHERE course_id = 'crs_a1') = 4
  AND (SELECT COUNT(*) FROM modules WHERE course_id = 'crs_a1' AND status = 'active'
       AND id IN ('mod_a1_1','mod_a1_2','mod_a1_3','mod_a1_4')) = 4
  AND (SELECT COUNT(*) FROM draft_modules WHERE course_id = 'crs_a1'
       AND id IN ('mod_a1_1','mod_a1_2','mod_a1_3','mod_a1_4')) = 4
  AND (SELECT COUNT(*) FROM draft_modules WHERE course_id = 'crs_a1') = 4
  AND sort_order != CASE id
                      WHEN 'mod_a1_1' THEN 1 WHEN 'mod_a1_2' THEN 2
                      WHEN 'mod_a1_3' THEN 3 WHEN 'mod_a1_4' THEN 4 END;

UPDATE draft_modules
SET sort_order = CASE id
                   WHEN 'mod_a1_1' THEN 1 WHEN 'mod_a1_2' THEN 2
                   WHEN 'mod_a1_3' THEN 3 WHEN 'mod_a1_4' THEN 4 END,
    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
WHERE course_id = 'crs_a1' AND id IN ('mod_a1_1','mod_a1_2','mod_a1_3','mod_a1_4')
  AND (SELECT COUNT(*) FROM modules WHERE course_id = 'crs_a1') = 4
  AND (SELECT COUNT(*) FROM modules WHERE course_id = 'crs_a1' AND status = 'active'
       AND id IN ('mod_a1_1','mod_a1_2','mod_a1_3','mod_a1_4')) = 4
  AND (SELECT COUNT(*) FROM draft_modules WHERE course_id = 'crs_a1'
       AND id IN ('mod_a1_1','mod_a1_2','mod_a1_3','mod_a1_4')) = 4
  AND (SELECT COUNT(*) FROM draft_modules WHERE course_id = 'crs_a1') = 4
  AND sort_order != CASE id
                      WHEN 'mod_a1_1' THEN 1 WHEN 'mod_a1_2' THEN 2
                      WHEN 'mod_a1_3' THEN 3 WHEN 'mod_a1_4' THEN 4 END;

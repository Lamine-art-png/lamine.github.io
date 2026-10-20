-- Reverses 0002_curriculum_seed.sql. Learner records tied to these courses are deleted by cascade; export first.
DELETE FROM question_banks WHERE course_id = 'crs_a1';
DELETE FROM video_assets WHERE id LIKE 'vid_a1_%';
DELETE FROM learning_paths WHERE id = 'pth_developer';
DELETE FROM learning_paths WHERE id = 'pth_student';
DELETE FROM learning_paths WHERE id = 'pth_operator';
DELETE FROM learning_paths WHERE id = 'pth_manager';
DELETE FROM learning_paths WHERE id = 'pth_agronomist';
DELETE FROM learning_paths WHERE id = 'pth_grower';
DELETE FROM courses WHERE id IN ('crs_a1', 'crs_a2', 'crs_a3', 'crs_a4', 'crs_a5', 'crs_a6', 'crs_b1', 'crs_b2', 'crs_b3', 'crs_b4', 'crs_b5', 'crs_b6', 'crs_b7', 'crs_b8', 'crs_b9', 'crs_b10', 'crs_c1', 'crs_c2', 'crs_c3', 'crs_c4', 'crs_c5', 'crs_c6', 'crs_d1', 'crs_d2', 'crs_d3', 'crs_d4', 'crs_d5', 'crs_d6', 'crs_e1', 'crs_e2', 'crs_e3', 'crs_e4', 'crs_e5', 'crs_e6');
DELETE FROM programs WHERE id = 'prg_a';
DELETE FROM programs WHERE id = 'prg_b';
DELETE FROM programs WHERE id = 'prg_c';
DELETE FROM programs WHERE id = 'prg_d';
DELETE FROM programs WHERE id = 'prg_e';
DELETE FROM instructors WHERE id = 'ins_faculty';
DELETE FROM instructors WHERE id = 'ins_joshua';

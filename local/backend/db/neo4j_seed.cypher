-- Neo4j constraints and indexes only — zero CREATE nodes
-- Applied by sample_data.py bootstrap

CREATE CONSTRAINT diagnosis_icd_unique IF NOT EXISTS
FOR (d:Diagnosis) REQUIRE d.icdCode IS UNIQUE;

CREATE CONSTRAINT service_type_name_unique IF NOT EXISTS
FOR (s:ServiceType) REQUIRE s.name IS UNIQUE;

CREATE CONSTRAINT certification_type_name_unique IF NOT EXISTS
FOR (c:CertificationType) REQUIRE c.name IS UNIQUE;

CREATE CONSTRAINT payer_name_unique IF NOT EXISTS
FOR (p:Payer) REQUIRE p.name IS UNIQUE;

CREATE CONSTRAINT insurance_plan_code_unique IF NOT EXISTS
FOR (i:InsurancePlan) REQUIRE i.code IS UNIQUE;

CREATE CONSTRAINT medication_generic_unique IF NOT EXISTS
FOR (m:Medication) REQUIRE m.genericName IS UNIQUE;

CREATE INDEX diagnosis_name_idx IF NOT EXISTS
FOR (d:Diagnosis) ON (d.name);

CREATE INDEX diagnosis_category_idx IF NOT EXISTS
FOR (d:Diagnosis) ON (d.category);

CREATE INDEX insurance_plan_name_idx IF NOT EXISTS
FOR (i:InsurancePlan) ON (i.name);

CREATE INDEX medication_name_idx IF NOT EXISTS
FOR (m:Medication) ON (m.name);

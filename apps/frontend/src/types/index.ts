export interface User {
  id: string;
  email: string;
  name: string;
  role: "admin" | "procurement_manager" | "analyst";
}

export interface AuthState {
  user: User | null;
  accessToken: string | null;
  isAuthenticated: boolean;
  setAuth: (token: string, user: User) => void;
  clearAuth: () => void;
}

export type SearchScope = 'approved_only' | 'both';

export interface ParsedConstraints {
  category?: string;
  location_name?: string;
  location_radius_km?: number;
  certifications?: string[];
  capacity_min?: number;
  capacity_unit?: string;
  lead_time_max_days?: number;
}

export type ComplianceStatus = "PASS" | "FAIL" | "PARTIAL";
export type ComplianceMatrix = Record<string, ComplianceStatus>;

// Task 1.5: structured, template-based explanation assembled from validated
// data (no LLM free text). Numbers trace to the supplier DB row.
export interface ExplanationDetail {
  match_reasons: string[];
  concerns: string[];
  facts: {
    capacity: string;
    lead_time: string;
    certifications: string[];
    location: string;
    tier: string;
  };
  summary: string;
}

export interface QueryResult {
  rank: number;
  supplier_id: string;
  supplier_name: string;
  supplier_city: string | null;
  supplier_country: string | null;
  supplier_lat: number | null;
  supplier_lng: number | null;
  supplier_certifications: string[] | null;
  supplier_capacity_value: number | null;
  supplier_capacity_unit: string | null;
  supplier_lead_time_days: number | null;
  supplier_website: string | null;
  supplier_source: string | null;
  supplier_status: 'approved' | 'saved' | 'discovered' | 'pending_review' | 'rejected' | null;
  tier: 'approved' | 'saved' | 'discovered' | 'pending_review' | null;
  // Task 1.6: present only when sanctions screening could not complete.
  sanctions_status?: 'pending_review' | null;
  total_score: number;
  constraint_score: number;
  semantic_score: number;
  proximity_score: number | null;
  completeness_score: number;
  compliance_matrix: ComplianceMatrix;
  explanation: string;
  explanation_detail: ExplanationDetail | null;
  distance_km: number | null;
  // Task 2.4 — HITL admin rationale, only present on approved/rejected suppliers.
  approval_justification?: string | null;
  approval_action?: 'approved' | 'rejected' | null;
  approval_decided_at?: string | null;
}

export interface Supplier {
  id: string;
  name: string;
  description: string | null;
  category: string | null;
  country: string | null;
  city: string | null;
  address: string | null;
  latitude: number | null;
  longitude: number | null;
  certifications: string[] | null;
  capacity_value: number | null;
  capacity_unit: string | null;
  lead_time_days: number | null;
  website: string | null;
  contact_email: string | null;
  source: string | null;
  status: 'approved' | 'saved' | 'discovered' | 'rejected';
  source_url: string | null;
  source_citations: Record<string, any> | null;
  is_active: boolean;
  created_at: string;
}

export interface QueryResponse {
  id: string;
  raw_query: string;
  status: "pending" | "processing" | "completed" | "failed" | "needs_clarification";
  detected_language?: string;
  parsed_constraints?: ParsedConstraints;
  execution_time_ms?: number;
  error_message?: string;
  created_at: string;
  completed_at?: string;
  results?: QueryResult[];
}

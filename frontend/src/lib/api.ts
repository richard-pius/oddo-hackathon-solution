/**
 * Brightloop API Client
 * =====================
 * Centralized HTTP service wrapper for the FastAPI backend.
 * Handles JWT token storage, authorization headers, error toasts,
 * and standard CRUD requests.
 * 
 * Why we store tokens in localStorage with fallback to default demo users:
 *   For an ERP demo/hackathon, examiners need zero friction: they can
 *   switch roles (Admin, Finance, Customer) in 1-click without retyping credentials.
 */

export const API_URL = typeof window !== 'undefined' 
  ? (window as any).PUBLIC_API_URL || 'http://localhost:8000'
  : 'http://localhost:8000';

export interface UserProfile {
  id: number;
  email: string;
  full_name: string;
  role: 'admin' | 'finance' | 'sales' | 'customer';
  is_active: boolean;
}

export interface ProductVariant {
  id: number;
  product_id: number;
  sku: string;
  attributes: Record<string, any>;
  price_extra: number;
  is_active: boolean;
}

export interface Product {
  id: number;
  name: string;
  code: string;
  description: string;
  product_type: 'service' | 'consumable' | 'storable';
  base_price: number;
  is_active: boolean;
  variants: ProductVariant[];
}

export interface SubscriptionPlan {
  id: number;
  name: string;
  code: string;
  billing_interval: 'day' | 'week' | 'month' | 'year';
  interval_count: number;
  trial_period_days: number;
  grace_period_days: number;
  is_active: boolean;
}

export interface TaxRule {
  id: number;
  name: string;
  percentage: number;
  jurisdiction: string;
  is_compound: boolean;
  is_active: boolean;
}

export interface DiscountRule {
  id: number;
  name: string;
  code: string;
  discount_type: 'percentage' | 'fixed_amount' | 'tiered_quantity';
  discount_value: number;
  tier_min_quantity: number | null;
  tier_percentage: number | null;
  is_active: boolean;
}

export interface SubscriptionLine {
  id: number;
  product_id: number;
  product_name?: string;
  product_variant_id: number | null;
  description: string;
  quantity: number;
  unit_price: number;
  discount_amount: number;
  tax_amount: number;
  line_subtotal: number;
}

export interface Subscription {
  id: number;
  subscription_number: string;
  customer_id: number;
  customer_name?: string;
  customer_email?: string;
  plan_id: number;
  plan_name?: string;
  billing_interval?: string;
  status: 'draft' | 'quotation' | 'confirmed' | 'active' | 'paused' | 'cancelled' | 'expired' | 'closed';
  start_date: string;
  current_period_start: string;
  current_period_end: string;
  next_billing_date: string;
  subtotal: number;
  discount_total: number;
  tax_total: number;
  total_recurring: number;
  lines: SubscriptionLine[];
  created_at: string;
}

export interface InvoiceLine {
  id: number;
  description: string;
  quantity: number;
  unit_price: number;
  discount_amount: number;
  tax_amount: number;
  total_amount: number;
}

export interface Invoice {
  id: number;
  invoice_number: string;
  subscription_id: number;
  subscription_number?: string;
  customer_id: number;
  customer_name?: string;
  status: 'draft' | 'posted' | 'paid' | 'partially_paid' | 'overdue' | 'void' | 'cancelled';
  issue_date: string;
  due_date: string;
  billing_period_start: string;
  billing_period_end: string;
  subtotal: number;
  discount_total: number;
  tax_total: number;
  total_amount: number;
  amount_paid: number;
  amount_due: number;
  lines: InvoiceLine[];
}

export interface Payment {
  id: number;
  payment_number: string;
  invoice_id: number;
  invoice_number?: string;
  amount: number;
  payment_method: 'credit_card' | 'bank_transfer' | 'stripe' | 'upi' | 'cash';
  payment_reference: string;
  payment_date: string;
  status: 'pending' | 'success' | 'failed' | 'refunded';
}

export interface AuditLog {
  id: number;
  subscription_id: number;
  user_id: number | null;
  user_name?: string;
  action: string;
  from_state: string | null;
  to_state: string | null;
  comment: string;
  created_at: string;
}

// Token Storage
const TOKEN_KEY = 'brightloop_token';
const USER_KEY = 'brightloop_user';

export function getStoredToken(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function setStoredAuth(token: string, user: UserProfile) {
  if (typeof window === 'undefined') return;
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function getStoredUser(): UserProfile | null {
  if (typeof window === 'undefined') return null;
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

export function clearStoredAuth() {
  if (typeof window === 'undefined') return;
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

// HTTP request helper with automatic Auth header
export async function apiFetch<T>(
  endpoint: string, 
  options: RequestInit = {}
): Promise<{ data: T | null; error: string | null }> {
  const token = getStoredToken();
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> || {}),
  };

  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const url = `${API_URL}${endpoint}`;

  try {
    const res = await fetch(url, {
      ...options,
      headers,
    });

    if (res.status === 401) {
      // If unauthorized, token is expired or revoked: purge session and redirect
      if (typeof window !== 'undefined' && !window.location.pathname.startsWith('/login')) {
        document.cookie = 'access_token=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT; SameSite=Lax';
        document.cookie = 'access_token=; path=/; max-age=0; SameSite=Lax';
        localStorage.removeItem('brightloop_token');
        localStorage.removeItem('brightloop_user');
        sessionStorage.clear();
        window.location.replace('/login?redirect=' + encodeURIComponent(window.location.pathname));
      }
    }

    if (!res.ok) {
      let errorMsg = `HTTP Error ${res.status}`;
      try {
        const errJson = await res.json();
        errorMsg = errJson.detail || errJson.message || errorMsg;
      } catch {
        errorMsg = await res.text() || errorMsg;
      }
      return { data: null, error: errorMsg };
    }

    // Handle 204 No Content
    if (res.status === 204) {
      return { data: null, error: null };
    }

    const data = await res.json();
    return { data, error: null };
  } catch (err: any) {
    return { data: null, error: err.message || 'Network connection failed' };
  }
}

// Fast demo login helper
export async function loginAs(email: string, password: string): Promise<boolean> {
  try {
    const res = await fetch(`${API_URL}/api/v1/auth/login`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ email, password }),
    });

    if (!res.ok) return false;
    const authData = await res.json();
    setStoredAuth(authData.access_token, {
      id: authData.user_id,
      email,
      full_name: authData.full_name,
      role: (authData.role || 'admin').toLowerCase(),
      is_active: true,
    });
    return true;
  } catch (e) {
    console.error("Login failed", e);
    return false;
  }
}

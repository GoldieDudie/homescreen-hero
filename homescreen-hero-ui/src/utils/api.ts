// Dispatch a custom event for demo mode blocks so the UI can show a toast
function fireDemoBlockedEvent() {
    window.dispatchEvent(new CustomEvent("demo-blocked"));
}

// Check if a response was blocked by demo mode guard
export function isDemoBlocked(response: Response): boolean {
    return response.status === 403 && response.headers.get("X-Demo-Blocked") === "true";
}

// Helper function to make authenticated API calls
export async function fetchWithAuth(
    url: string,
    options: RequestInit = {}
): Promise<Response> {
    const token = localStorage.getItem("auth_token");

    const headers: Record<string, string> = {
        ...(options.headers as Record<string, string> || {}),
    };

    // Add Authorization header if token exists
    if (token) {
        headers["Authorization"] = `Bearer ${token}`;
    }

    const response = await fetch(url, {
        ...options,
        headers,
    });

    // Demo mode blocks return 403 with X-Demo-Blocked header - don't logout
    if (response.status === 403 && response.headers.get("X-Demo-Blocked")) {
        fireDemoBlockedEvent();
        return response;
    }

    // 401 = invalid/expired token, 403 = account removed or pending
    if (response.status === 401 || response.status === 403) {
        localStorage.removeItem("auth_token");
        localStorage.removeItem("username");
        localStorage.removeItem("role");
        localStorage.removeItem("thumb");
        window.location.href = "/login";
    }

    return response;
}

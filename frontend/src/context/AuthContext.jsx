import React, { createContext, useContext, useState, useEffect } from 'react';
import axios from 'axios';
import { jwtDecode } from 'jwt-decode';

const AuthContext = createContext();

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  // Standalone helper declared before useEffect so it can be called during
  // the initial token-validation pass without a hoisting error.
  const doLogout = () => {
    localStorage.removeItem('token');
    // Legacy cleanup: the Automation launcher used to stash the plaintext password here.
    // It is no longer written, but anyone who logged in before that change still has one
    // sitting in localStorage — this clears it on their next logout. Safe to delete once
    // every active session has cycled.
    localStorage.removeItem('sparsh_pwd');
    setUser(null);
    delete axios.defaults.headers.common['Authorization'];
  };

  useEffect(() => {
    const token = localStorage.getItem('token');
    const fetchUser = async (tokenData) => {
      try {
        const API_URL = import.meta.env.VITE_API_BASE_URL || '/api';
        const response = await axios.get(`${API_URL}/users/me`);
        const fullUser = { ...tokenData, ...response.data };
        // Ensure _id exists (compatibility between JWT and API aliases)
        if (!fullUser._id && fullUser.id) fullUser._id = fullUser.id;
        setUser(fullUser);
      } catch (err) {
        console.error("Profile fetch error:", err);
      }
    };

    if (token) {
      try {
        const decoded = jwtDecode(token);
        if (decoded.exp * 1000 < Date.now()) {
          // eslint-disable-next-line react-hooks/set-state-in-effect
          doLogout();
        } else {
          setUser(decoded); // Immediate load from token
          axios.defaults.headers.common['Authorization'] = `Bearer ${token}`;
          fetchUser(decoded); // Background load full profile
        }
      } catch (err) {
        // eslint-disable-next-line react-hooks/set-state-in-effect
        doLogout();
      }
    }
    setLoading(false);
  }, []);

  const login = async (username, password) => {
    const formData = new FormData();
    formData.append('username', username);
    formData.append('password', password);

    const API_URL = import.meta.env.VITE_API_BASE_URL || '/api';
    const response = await axios.post(`${API_URL}/auth/token`, formData);
    const { access_token } = response.data;

    localStorage.setItem('token', access_token);
    const decoded = jwtDecode(access_token);
    setUser(decoded);
    axios.defaults.headers.common['Authorization'] = `Bearer ${access_token}`;
    
    // Fetch full profile info
    try {
      const profileResponse = await axios.get(`${API_URL}/users/me`);
      const fullUser = { ...decoded, ...profileResponse.data };
      if (!fullUser._id && fullUser.id) fullUser._id = fullUser.id;
      setUser(fullUser);
    } catch (err) {
      console.error("Full profile fetch failed after login", err);
    }
    
    return decoded;
  };

  // Context-facing logout delegates to doLogout so callers get a stable reference.
  const logout = doLogout;

  // Re-pull the full profile from /users/me and merge it into the current user, so edits
  // made in Settings ▸ General (name, etc.) reflect immediately in the header/avatar.
  const refreshUser = async () => {
    try {
      const API_URL = import.meta.env.VITE_API_BASE_URL || '/api';
      const response = await axios.get(`${API_URL}/users/me`);
      setUser(prev => {
        const merged = { ...(prev || {}), ...response.data };
        if (!merged._id && merged.id) merged._id = merged.id;
        return merged;
      });
      return response.data;
    } catch (err) {
      console.error("Profile refresh error:", err);
    }
  };

  return (
    <AuthContext.Provider value={{ user, login, logout, loading, refreshUser }}>
      {!loading && children}
    </AuthContext.Provider>
  );
};

// eslint-disable-next-line react-refresh/only-export-components
export const useAuth = () => useContext(AuthContext);

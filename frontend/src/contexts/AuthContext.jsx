import { createContext, useContext, useState, useEffect } from 'react';
import { authAPI } from '../lib/api';

const AuthContext = createContext(null);

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem('access_token');
    if (token) {
      // Fetch user profile with permissions
      authAPI.getCurrentUser()
        .then(response => {
          setUser({
            authenticated: true,
            username: response.data.username,
            email: response.data.email,
            is_staff: response.data.is_staff,
            is_superuser: response.data.is_superuser,
            first_name: response.data.first_name,
            last_name: response.data.last_name,
          });
        })
        .catch(() => {
          // Token invalid, clear storage
          authAPI.logout();
          setUser(null);
        })
        .finally(() => {
          setLoading(false);
        });
    } else {
      setLoading(false);
    }
  }, []);

  const login = async (username, password) => {
    const response = await authAPI.login(username, password);
    const { access, refresh } = response.data;
    
    localStorage.setItem('access_token', access);
    localStorage.setItem('refresh_token', refresh);
    
    // Fetch user profile with permissions
    const profileResponse = await authAPI.getCurrentUser();
    setUser({
      authenticated: true,
      username: profileResponse.data.username,
      email: profileResponse.data.email,
      is_staff: profileResponse.data.is_staff,
      is_superuser: profileResponse.data.is_superuser,
      first_name: profileResponse.data.first_name,
      last_name: profileResponse.data.last_name,
    });
    
    return response.data;
  };

  const logout = () => {
    authAPI.logout();
    setUser(null);
  };

  const register = async (data) => {
    const response = await authAPI.register(data);
    return response.data;
  };

  return (
    <AuthContext.Provider value={{ user, login, logout, register, loading }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider');
  }
  return context;
};

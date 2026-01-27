import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { Home, Package, Boxes, Archive, LogOut, List, Settings } from 'lucide-react';

export default function Layout({ children }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  return (
    <div className="min-h-screen bg-gray-900">
      {/* Sidebar */}
      <div className="fixed inset-y-0 left-0 w-64 bg-gray-800 shadow-lg">
        <div className="flex flex-col h-full">
          {/* Logo */}
          <div className="flex items-center justify-center h-16 bg-gray-900">
            <h1 className="text-2xl font-bold text-white">ReqPM</h1>
          </div>

          {/* Navigation */}
          <nav className="flex-1 px-4 py-6 space-y-2">
            <NavLink to="/" icon={<Home size={20} />}>
              Dashboard
            </NavLink>
            <NavLink to="/projects" icon={<Package size={20} />}>
              Projects
            </NavLink>
            <NavLink to="/packages" icon={<Boxes size={20} />}>
              Packages
            </NavLink>
            <NavLink to="/builds" icon={<Boxes size={20} />}>
              Builds
            </NavLink>
            <NavLink to="/repositories" icon={<Archive size={20} />}>
              Repositories
            </NavLink>
            <NavLink to="/tasks" icon={<List size={20} />}>
              Tasks
            </NavLink>
            
            {/* Admin-only Settings */}
            {(user?.is_staff || user?.is_superuser) && (
              <div className="pt-4 mt-4 border-t border-gray-700">
                <NavLink to="/settings" icon={<Settings size={20} />}>
                  Settings
                </NavLink>
              </div>
            )}
          </nav>

          {/* User section */}
          <div className="p-4 border-t border-gray-700">
            <div className="flex items-center justify-between">
              <span className="text-sm text-gray-300">{user?.username || 'User'}</span>
              <button
                onClick={handleLogout}
                className="p-2 text-gray-400 hover:text-white hover:bg-gray-700 rounded-lg transition-colors"
                title="Logout"
              >
                <LogOut size={20} />
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Main content */}
      <div className="ml-64 min-h-screen">
        <main className="p-8">
          {children}
        </main>
      </div>
    </div>
  );
}

function NavLink({ to, icon, children }) {
  return (
    <Link
      to={to}
      className="flex items-center space-x-3 px-4 py-3 text-gray-300 hover:bg-gray-700 hover:text-white rounded-lg transition-colors"
    >
      {icon}
      <span>{children}</span>
    </Link>
  );
}

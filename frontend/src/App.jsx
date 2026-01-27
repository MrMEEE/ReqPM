import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider } from './contexts/AuthContext';
import { ProtectedRoute } from './components/ProtectedRoute';
import Layout from './components/Layout';
import Login from './pages/Login';
import Register from './pages/Register';
import Dashboard from './pages/Dashboard';
import Projects from './pages/Projects';
import ProjectDetail from './pages/ProjectDetail';
import Packages from './pages/Packages';
import PackageDetail from './pages/PackageDetail';
import Builds from './pages/Builds';
import BuildDetail from './pages/BuildDetail';
import Repositories from './pages/Repositories';
import Tasks from './pages/Tasks';
import Settings from './pages/Settings';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <Router>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route path="/register" element={<Register />} />
            
            <Route
              path="/"
              element={
                <ProtectedRoute>
                  <Layout>
                    <Dashboard />
                  </Layout>
                </ProtectedRoute>
              }
            />
            
            <Route
              path="/projects"
              element={
                <ProtectedRoute>
                  <Layout>
                    <Projects />
                  </Layout>
                </ProtectedRoute>
              }
            />
            
            <Route
              path="/projects/:id"
              element={
                <ProtectedRoute>
                  <Layout>
                    <ProjectDetail />
                  </Layout>
                </ProtectedRoute>
              }
            />
            
            <Route
              path="/packages"
              element={
                <ProtectedRoute>
                  <Layout>
                    <Packages />
                  </Layout>
                </ProtectedRoute>
              }
            />
            
            <Route
              path="/packages/:id"
              element={
                <ProtectedRoute>
                  <Layout>
                    <PackageDetail />
                  </Layout>
                </ProtectedRoute>
              }
            />
            
            <Route
              path="/builds"
              element={
                <ProtectedRoute>
                  <Layout>
                    <Builds />
                  </Layout>
                </ProtectedRoute>
              }
            />
            
            <Route
              path="/builds/:id"
              element={
                <ProtectedRoute>
                  <Layout>
                    <BuildDetail />
                  </Layout>
                </ProtectedRoute>
              }
            />
            
            <Route
              path="/repositories"
              element={
                <ProtectedRoute>
                  <Layout>
                    <Repositories />
                  </Layout>
                </ProtectedRoute>
              }
            />
            
            <Route
              path="/tasks"
              element={
                <ProtectedRoute>
                  <Layout>
                    <Tasks />
                  </Layout>
                </ProtectedRoute>
              }
            />
            
            <Route
              path="/settings"
              element={
                <ProtectedRoute>
                  <Layout>
                    <Settings />
                  </Layout>
                </ProtectedRoute>
              }
            />
            
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Router>
      </AuthProvider>
    </QueryClientProvider>
  );
}

export default App;


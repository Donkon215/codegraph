// React frontend — OrderList component calling the Python backend
import React, { useEffect, useState } from 'react';
import axios from 'axios';

/** Shared contract — matches OrderModel on the Python backend. */
interface OrderDTO {
  id: string;
  user_id: string;
  items: string[];
  total: number;
}

/** Shared contract — matches UserModel on the Python backend. */
interface UserDTO {
  id: string;
  name: string;
  email: string;
}

const OrderList: React.FC = () => {
  const [orders, setOrders] = useState<OrderDTO[]>([]);
  const [currentUser, setCurrentUser] = useState<UserDTO | null>(null);

  useEffect(() => {
    // cross-language link: fetch('/api/orders') → backend/api.py::get_orders
    fetch('/api/orders')
      .then(r => r.json())
      .then(setOrders);

    // cross-language link: axios.get('/api/users') → backend/api.py::get_users
    axios.get('/api/users')
      .then(r => setCurrentUser(r.data[0] ?? null));
  }, []);

  const placeOrder = async () => {
    // cross-language link: axios.post('/api/orders') → backend/api.py::create_order
    const result = await axios.post('/api/orders', { items: ['item_a'] });
    setOrders(prev => [...prev, result.data]);
  };

  return (
    <div>
      <h1>Orders for {currentUser?.name ?? 'Guest'}</h1>
      <button onClick={placeOrder}>Place Order</button>
      <ul>
        {orders.map(o => (
          <li key={o.id}>{o.id} — ${o.total}</li>
        ))}
      </ul>
    </div>
  );
};

export default OrderList;
